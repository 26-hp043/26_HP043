import { describe, expect, it, vi } from 'vitest'
import { createApiNotUnderwayProvider, NotUnderwayError } from './apiProvider'
import type { PeriodDraft } from './types'

/**
 * not under way 구간 provider 계약 (`API_SPEC §2.9~§2.13` · `#370`).
 *
 * 여기서 고정하는 것은 셋이다.
 *
 * * **CF를 보내지 않는 것** — 배출계수는 서버가 계산 시점 값으로 뜬다. 화면이 보내면
 *   사용자가 배출계수를 정하는 셈이 되고 `PRD §8.4`가 무너진다.
 * * **선택지를 서버에서 받는 것** — 화면이 열거값을 자기 코드에 박으면 DB CHECK
 *   제약·연료 seed와 갈라지고, 사용자는 저장 단계에서야 거부를 만난다. 상태 열거값은
 *   이 리소스의 `meta`에서, **연료는 `/parameters/fuel-types`에서** 온다 (`#444`).
 * * **서버 오류 문구를 그대로 쓰는 것** — 겹침(409)은 상대 구간의 시각까지 실어 온다.
 */

const DRAFT: PeriodDraft = {
  periodType: 'AT_ANCHOR',
  startedAt: '2026-08-10T14:00:00.000Z',
  endedAt: '2026-08-12T09:00:00.000Z',
  portName: '부산',
  distanceNm: '0',
  fuelUses: [{ consumerType: 'OIL_FIRED_BOILER', fuelType: 'HFO', fuelTon: '12' }],
}

/** 실제 서버 응답에서 가져온 형태 (2026-08-17 실측). */
const PERIOD_BODY = {
  data: {
    id: '82bab83d-9d31-4880-b8b8-23f207d13477',
    vessel_id: '00000000-0000-4000-8000-000000000003',
    regulation_year: 2026,
    period_type: 'AT_ANCHOR',
    started_at: '2026-08-10T14:00:00+00:00',
    ended_at: '2026-08-12T09:00:00+00:00',
    port_name: '부산',
    lat: null,
    lon: null,
    distance_nm: 0.0,
    voyage_id: null,
    fuel_uses: [
      {
        id: '27d0b3fe-460f-4aa2-88ee-53776a0e5f79',
        period_id: '82bab83d-9d31-4880-b8b8-23f207d13477',
        consumer_type: 'OIL_FIRED_BOILER',
        fuel_type: 'HFO',
        fuel_ton: 12.0,
        cf_used: 3.114,
      },
    ],
    created_at: '2026-08-16T17:03:20.001074+00:00',
  },
  meta: {},
}

const LIST_BODY = {
  data: [
    {
      ...PERIOD_BODY.data,
      id: '00000000-0000-4000-8000-000000000202',
      ended_at: null,
      fuel_uses: [],
    },
  ],
  meta: {
    total: 1,
    period_types: ['IN_PORT', 'AT_ANCHOR', 'DRIFTING', 'STS', 'CANAL_TRANSIT', 'DRYDOCK'],
    consumer_types: ['MAIN_ENGINE', 'AUX_ENGINE', 'OIL_FIRED_BOILER', 'OTHER'],
  },
}

/** `API_SPEC §7.2` 응답 (`#444`). `cf`는 문자열이다 — `§1.7`. */
const FUEL_TYPES_BODY = {
  data: [
    { code: 'DIESEL_GAS_OIL', display_name: 'Diesel/Gas Oil', cf: '3.206000', unit: 'tCO₂/tFuel', is_active: true },
    { code: 'HFO', display_name: 'Heavy Fuel Oil', cf: '3.114000', unit: 'tCO₂/tFuel', is_active: true },
    { code: 'LNG', display_name: 'Liquefied Natural Gas', cf: '2.750000', unit: 'tCO₂/tFuel', is_active: true },
  ],
  meta: { total: 3 },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const VESSEL = '00000000-0000-4000-8000-000000000003'

/**
 * 경로별로 다른 본문을 준다.
 *
 * 목록 조회가 **두 엔드포인트**를 부르게 됐으므로(`#444`), 한 본문을 모든 요청에
 * 돌려주면 연료 응답 자리에 구간 목록이 들어간다 — 그 상태는 실제 서버와 다르다.
 */
function routedFetch(listBody: unknown = LIST_BODY, fuelBody: unknown = FUEL_TYPES_BODY) {
  return vi.fn(async (input: URL | RequestInfo) =>
    jsonResponse(String(input).includes('/parameters/fuel-types') ? fuelBody : listBody),
  )
}

describe('목록', () => {
  it('선택지를 서버에서 받는다 — 화면이 열거값을 박지 않는다', async () => {
    const fetchImpl = routedFetch()
    const result = await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    expect(result.periodTypes).toHaveLength(6)
    expect(result.consumerTypes).toContain('OIL_FIRED_BOILER')
    expect(result.fuelTypes).toEqual(['DIESEL_GAS_OIL', 'HFO', 'LNG'])
  })

  it('연료 목록을 §7.2 엔드포인트에서 받는다 — 구간 meta의 우회를 쓰지 않는다', async () => {
    // `#444` 이전에는 구간 목록 응답의 `meta.fuel_types`를 읽었다. 남겨 두면 연료
    // 목록을 주는 곳이 화면마다 달라진다.
    const fetchImpl = routedFetch()
    await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    const urls = fetchImpl.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.endsWith('/parameters/fuel-types'))).toBe(true)
  })

  it('구간 meta에 연료가 실려 와도 그것을 쓰지 않는다', async () => {
    // 서버가 옛 필드를 남겨 두더라도 화면은 §7.2만 본다 — 두 목록이 갈릴 때
    // 조용히 낡은 쪽을 쓰는 일이 없어야 한다.
    const stale = { ...LIST_BODY, meta: { ...LIST_BODY.meta, fuel_types: ['STALE'] } }
    const fetchImpl = routedFetch(stale)
    const result = await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    expect(result.fuelTypes).not.toContain('STALE')
  })

  it('진행 중 구간의 endedAt을 null로 둔다 — 「모름」으로 바꾸지 않는다', async () => {
    const fetchImpl = routedFetch()
    const result = await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    expect(result.periods[0].endedAt).toBeNull()
  })

  it('연료가 없는 구간도 빈 배열로 준다', async () => {
    const fetchImpl = routedFetch()
    const result = await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    expect(result.periods[0].fuelUses).toEqual([])
  })

  it('선택지가 없으면 빈 배열이다 — 기본값을 지어 내지 않는다', async () => {
    const fetchImpl = routedFetch({ data: [], meta: {} }, { data: [], meta: {} })
    const result = await createApiNotUnderwayProvider(fetchImpl).list(VESSEL)

    expect(result.periodTypes).toEqual([])
    expect(result.fuelTypes).toEqual([])
  })
})

describe('생성', () => {
  it('요청 필드를 API_SPEC §2.10 이름으로 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(PERIOD_BODY, 201))
    await createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT)

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe(`/api/v1/vessels/${VESSEL}/not-underway-periods`)
    expect((init as RequestInit).method).toBe('POST')

    const sent = JSON.parse((init as RequestInit).body as string)
    expect(sent).toMatchObject({
      period_type: 'AT_ANCHOR',
      started_at: DRAFT.startedAt,
      ended_at: DRAFT.endedAt,
      port_name: '부산',
      distance_nm: 0,
    })
    expect(sent.fuel_uses[0]).toEqual({
      consumer_type: 'OIL_FIRED_BOILER',
      fuel_type: 'HFO',
      fuel_ton: 12,
    })
  })

  it('CF를 보내지 않는다 — 배출계수는 서버가 뜬다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(PERIOD_BODY, 201))
    await createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT)

    const sent = JSON.parse((fetchImpl.mock.calls[0][1] as RequestInit).body as string)
    expect(sent.fuel_uses[0]).not.toHaveProperty('cf_used')
  })

  it('규제연도를 보내지 않는다 — 서버가 시작 시각의 연도로 채운다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(PERIOD_BODY, 201))
    await createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT)

    const sent = JSON.parse((fetchImpl.mock.calls[0][1] as RequestInit).body as string)
    expect(sent).not.toHaveProperty('regulation_year')
  })

  it('서버가 뜬 CF를 응답에서 받아 온다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(PERIOD_BODY, 201))
    const period = await createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT)

    expect(period.fuelUses[0].cfUsed).toBe(3.114)
  })
})

describe('종료 확정 · 삭제', () => {
  it('종료 시각만 PATCH 한다 — 나머지는 생략 = 변경 없음이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(PERIOD_BODY))
    await createApiNotUnderwayProvider(fetchImpl).close('p-1', '2026-08-12T09:00:00.000Z')

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/not-underway-periods/p-1')
    expect((init as RequestInit).method).toBe('PATCH')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      ended_at: '2026-08-12T09:00:00.000Z',
    })
  })

  it('삭제는 DELETE 한 번이다', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ data: { id: 'p-1', deleted: true } }))
    await createApiNotUnderwayProvider(fetchImpl).remove('p-1')

    expect((fetchImpl.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})

describe('실패 경로', () => {
  it('겹침(409)의 서버 문구를 그대로 쓴다 — 상대 구간의 시각이 담겨 있다', async () => {
    const message =
      '같은 선박에 이미 겹치는 구간이 있습니다 (2026-08-10T14:00:00+00:00 ~ 진행 중). ' +
      '기존 구간의 종료 시각을 먼저 확정해 주세요.'
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ error: { code: 'CONFLICT', message } }, 409))

    await expect(
      createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT),
    ).rejects.toThrow(message)
  })

  it('422 검증 오류의 field를 옮긴다 — 화면이 입력창에 붙일 수 있어야 한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: '알 수 없는 연료 종류입니다: MDO',
            details: [{ field: 'fuel_type', message: '알 수 없는 연료 종류입니다: MDO' }],
          },
        },
        422,
      ),
    )

    await expect(
      createApiNotUnderwayProvider(fetchImpl).create(VESSEL, DRAFT),
    ).rejects.toMatchObject({ field: 'fuel_type' })
  })

  it('네트워크 실패를 삼키지 않고 원인을 보존한다', async () => {
    const cause = new TypeError('Failed to fetch')
    const fetchImpl = vi.fn().mockRejectedValue(cause)

    const promise = createApiNotUnderwayProvider(fetchImpl).list(VESSEL)
    await expect(promise).rejects.toBeInstanceOf(NotUnderwayError)
    await expect(promise).rejects.toMatchObject({ cause })
  })
})
