import { describe, expect, it, vi } from 'vitest'
import { createApiVoyageManagementProvider, VoyageError } from './apiProvider'
import { toIsoInstant } from './voyageRules'
import type { ActualsDraft, ManagedVoyage, VoyageDraft } from './types'

/**
 * 항차 관리 provider 계약 (`API_SPEC §3.3`·`§3.5`·`§3.6` · `#610`).
 *
 * 여기서 고정하는 것은 넷이다.
 *
 * * **생성 시 policy·status를 보내지 않는 것** — `§3.3` [EXT-P0-4]. 결과는 항상
 *   `DRAFT` · `EXCLUDE`이고 그것은 서버가 정한다.
 * * **전환 시 policy를 언제 싣는지** — 생략은 현행 유지인데, 목표 상태가 현행을
 *   허용하지 않으면 서버가 **자동 보정하지 않고 422로 거부**한다. 데모 마지막
 *   걸음(`IN_PROGRESS(INCLUDE_AS_PLAN) → COMPLETED`)이 정확히 그 경우다.
 * * **실적 본문에 계획값이 없는 것** — `PRD §8.4` 계획값 보존. 계획 대비 실적
 *   차이가 `#363` 피드백 루프의 입력이라 잃으면 비교가 영영 불가능해진다.
 * * **서버 오류 문구를 그대로 쓰는 것** — 전환 가드가 왜 막혔는지는 서버가 안다.
 */

const VOYAGE_BODY = {
  data: {
    id: 'f0a1',
    voyage_no: 'V-2026-001',
    status: 'IN_PROGRESS',
    annual_inclusion_policy: 'INCLUDE_AS_PLAN',
    regulation_year: 2026,
    departure_port_name: 'Busan',
    arrival_port_name: 'Rotterdam',
    planned_distance_nm: 11000.0,
    planned_speed_kn: 14.0,
    actual_distance_nm: null,
    actual_avg_speed_kn: null,
    fuel_uses: [
      { fuel_type: 'HFO', planned_fuel_ton: 800.0, actual_fuel_ton: null },
    ],
  },
}

const FUEL_TYPES_BODY = {
  data: [{ code: 'HFO', display_name: 'Heavy Fuel Oil', cf: '3.114', unit: 't', is_active: true }],
}

const DRAFT: VoyageDraft = {
  voyageNo: 'V-2026-002',
  departurePortName: 'Busan',
  arrivalPortName: 'Singapore',
  plannedDistanceNm: '2800',
  plannedSpeedKn: '13.5',
  plannedDepartureAt: '',
  plannedArrivalAt: '',
  regulationYear: '2026',
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: '210' }],
}

const VOYAGE: ManagedVoyage = {
  id: 'f0a1',
  voyageNo: 'V-2026-001',
  status: 'IN_PROGRESS',
  inclusionPolicy: 'INCLUDE_AS_PLAN',
  regulationYear: 2026,
  departurePortName: 'Busan',
  arrivalPortName: 'Rotterdam',
  plannedDistanceNm: 11000,
  plannedSpeedKn: 14,
  actualDistanceNm: null,
  actualAvgSpeedKn: null,
  plannedDepartureAt: null,
  plannedArrivalAt: null,
  actualDepartureAt: null,
  actualArrivalAt: null,
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 800, actualFuelTon: 850 }],
}

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

function fail(status: number, body: unknown): Response {
  return { ok: false, status, json: async () => body } as unknown as Response
}

/** 경로로 갈라 응답을 돌려주는 fake. 마지막 요청 본문을 꺼내 볼 수 있다. */
function fakeFetch(routes: Record<string, Response>) {
  return vi.fn(async (url: string) => {
    for (const [fragment, response] of Object.entries(routes)) {
      if (url.includes(fragment)) return response
    }
    throw new Error(`예상하지 못한 요청: ${url}`)
  }) as unknown as typeof globalThis.fetch
}

function bodyOf(fetchMock: unknown, index = 0): Record<string, unknown> {
  const calls = (fetchMock as { mock: { calls: unknown[][] } }).mock.calls
  const init = calls[index][1] as RequestInit
  return JSON.parse(String(init.body))
}

describe('list', () => {
  it('항차와 연료 선택지를 함께 가져온다 — 연료는 /parameters/fuel-types에서 온다', async () => {
    const fetchMock = fakeFetch({
      '/parameters/fuel-types': ok(FUEL_TYPES_BODY),
      '/voyages': ok({ data: [VOYAGE_BODY.data] }),
    })
    const provider = createApiVoyageManagementProvider(fetchMock, '')

    const result = await provider.list('v-1')

    expect(result.fuelTypes).toEqual(['HFO'])
    expect(result.voyages[0].voyageNo).toBe('V-2026-001')
    expect(result.voyages[0].plannedDistanceNm).toBe(11000)
  })

  /*
   * 커서 페이지네이션 (`#627`).
   *
   * 종전에는 `?limit=100`만 박고 `meta.next_cursor`를 버렸다. `#625`가 한 번에
   * 1,000행을 넣을 수 있게 만든 뒤 **101번째부터 화면에서 도달할 방법이 없었다.**
   */
  it('meta의 커서를 읽어 돌려준다 — 버리면 101번째부터 도달할 수 없다', async () => {
    const fetchMock = fakeFetch({
      '/parameters/fuel-types': ok(FUEL_TYPES_BODY),
      '/voyages': ok({
        data: [VOYAGE_BODY.data],
        meta: { next_cursor: 'c-2', has_more: true },
      }),
    })
    const provider = createApiVoyageManagementProvider(fetchMock, '')

    const result = await provider.list('v-1')

    expect(result.nextCursor).toBe('c-2')
    expect(result.hasMore).toBe(true)
  })

  it('커서를 받으면 쿼리에 실어 보낸다 — 인코딩한다', async () => {
    const fetchMock = fakeFetch({
      '/parameters/fuel-types': ok(FUEL_TYPES_BODY),
      '/voyages': ok({ data: [], meta: { has_more: false } }),
    })
    const provider = createApiVoyageManagementProvider(fetchMock, '')

    await provider.list('v-1', 'a b/c')

    const calls = (fetchMock as unknown as { mock: { calls: unknown[][] } }).mock.calls
    const url = String(calls.map((c) => c[0]).find((u) => String(u).includes('/voyages')))
    expect(url).toContain('limit=100')
    expect(url).toContain('cursor=a%20b%2Fc')
  })

  it('meta가 없으면 「더 없음」으로 읽는다 — 커서를 지어내면 같은 페이지를 무한히 부른다', async () => {
    const fetchMock = fakeFetch({
      '/parameters/fuel-types': ok(FUEL_TYPES_BODY),
      '/voyages': ok({ data: [VOYAGE_BODY.data] }),
    })
    const provider = createApiVoyageManagementProvider(fetchMock, '')

    const result = await provider.list('v-1')

    expect(result.nextCursor).toBeNull()
    expect(result.hasMore).toBe(false)
  })
})

describe('create — API_SPEC §3.3', () => {
  it('status와 annual_inclusion_policy를 보내지 않는다 (EXT-P0-4)', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', DRAFT)

    const sent = bodyOf(fetchMock)
    expect(sent).not.toHaveProperty('status')
    expect(sent).not.toHaveProperty('annual_inclusion_policy')
    expect(sent.planned_distance_nm).toBe(2800)
  })

  it('기준연도가 비어 있으면 키 자체를 넣지 않는다 — optional이다 (#150)', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', {
      ...DRAFT,
      regulationYear: '',
    })

    expect(bodyOf(fetchMock)).not.toHaveProperty('regulation_year')
  })

  /*
   * 시각 2종 (#873). 종전에는 이 두 키가 본문에 **아예 없었다** — 프론트 전체에서
   * 참조 0건이었다. 서버는 `§3.3`에서 처음부터 받고 있었다.
   */
  it('입력한 계획 시각을 UTC 문자열로 보낸다', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', {
      ...DRAFT,
      plannedDepartureAt: '2026-06-01T09:00',
      plannedArrivalAt: '2026-06-08T09:00',
    })

    const sent = bodyOf(fetchMock)
    expect(typeof sent.planned_departure_at).toBe('string')
    expect(sent.planned_departure_at).toBe(toIsoInstant('2026-06-01T09:00'))
    expect(sent.planned_arrival_at).toBe(toIsoInstant('2026-06-08T09:00'))
  })

  it('시각이 비어 있으면 키 자체를 넣지 않는다 — optional이다 (§3.3)', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', DRAFT)

    const sent = bodyOf(fetchMock)
    expect(sent).not.toHaveProperty('planned_departure_at')
    expect(sent).not.toHaveProperty('planned_arrival_at')
  })

  it('연료 여러 줄을 그대로 fuel_uses[]로 보낸다 (#636)', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', {
      ...DRAFT,
      fuelUses: [
        { fuelType: 'HFO', plannedFuelTon: '800' },
        { fuelType: 'DIESEL_GAS_OIL', plannedFuelTon: '40' },
      ],
    })

    expect(bodyOf(fetchMock).fuel_uses).toEqual([
      { fuel_type: 'HFO', planned_fuel_ton: 800, source: 'USER_INPUT' },
      { fuel_type: 'DIESEL_GAS_OIL', planned_fuel_ton: 40, source: 'USER_INPUT' },
    ])
  })

  it('한 줄이어도 배열로 보낸다 — 계약이 배열이다 (§3.3)', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', DRAFT)

    expect(bodyOf(fetchMock).fuel_uses).toHaveLength(1)
  })

  it('source는 USER_INPUT이다 — 사용자가 직접 넣은 값이다', async () => {
    const fetchMock = fakeFetch({ '/voyages': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').create('v-1', DRAFT)

    for (const fu of bodyOf(fetchMock).fuel_uses as Array<Record<string, unknown>>) {
      expect(fu.source).toBe('USER_INPUT')
    }
  })
})

describe('transition — API_SPEC §3.5', () => {
  it('계획 반영 항차를 완료로 옮길 때 실적 반영을 명시한다', async () => {
    /*
     * 생략하면 현행(`INCLUDE_AS_PLAN`)이 유지되는데 `COMPLETED`는 그것을 받지
     * 않는다. 서버는 자동 보정하지 않고 422를 낸다 — 데모가 여기서 끊긴다.
     */
    const fetchMock = fakeFetch({ '/transition': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').transition(VOYAGE, 'COMPLETED')

    expect(bodyOf(fetchMock)).toEqual({
      to_status: 'COMPLETED',
      annual_inclusion_policy: 'INCLUDE_AS_ACTUAL',
    })
  })

  it('목표 상태가 현행을 허용하면 policy를 생략한다', async () => {
    const fetchMock = fakeFetch({ '/transition': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').transition(
      { ...VOYAGE, status: 'PLANNED' },
      'IN_PROGRESS',
    )

    expect(bodyOf(fetchMock)).toEqual({ to_status: 'IN_PROGRESS' })
  })

  it('정책을 명시하면 그것을 싣는다 — 기능① 계획 저장의 연간 반영 (#891)', async () => {
    /*
     * `DRAFT → PLANNED`에서 규칙은 현행(`EXCLUDE`)을 유지해 policy를 생략한다. 계획 저장이
     * 연간 반영을 고르면 그 규칙을 넘어서 `INCLUDE_AS_PLAN`을 실어야 한다 — 싣지 않으면
     * 저장은 되는데 **기능③에 조용히 반영되지 않는다.**
     */
    const fetchMock = fakeFetch({ '/transition': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').transition(
      { ...VOYAGE, status: 'DRAFT', inclusionPolicy: 'EXCLUDE' },
      'PLANNED',
      'INCLUDE_AS_PLAN',
    )

    expect(bodyOf(fetchMock)).toEqual({
      to_status: 'PLANNED',
      annual_inclusion_policy: 'INCLUDE_AS_PLAN',
    })
  })
})

describe('saveActuals — API_SPEC §3.6', () => {
  const draft: ActualsDraft = {
    actualDistanceNm: '11200',
    actualAvgSpeedKn: '',
    actualDepartureAt: '',
    actualArrivalAt: '',
    actualFuelTon: { HFO: '850' },
  }

  it('계획값을 싣지 않는다 — PRD §8.4', async () => {
    const fetchMock = fakeFetch({ '/actuals': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').saveActuals('f0a1', draft)

    const sent = bodyOf(fetchMock)
    expect(JSON.stringify(sent)).not.toMatch(/planned/)
    expect(sent).toEqual({
      actual_distance_nm: 11200,
      fuel_uses: [{ fuel_type: 'HFO', actual_fuel_ton: 850, source: 'USER_INPUT' }],
    })
  })

  it('빈 칸은 키 자체를 보내지 않는다 — 생략이 「변경 없음」이다', async () => {
    const fetchMock = fakeFetch({ '/actuals': ok(VOYAGE_BODY) })
    await createApiVoyageManagementProvider(fetchMock, '').saveActuals('f0a1', draft)

    expect(bodyOf(fetchMock)).not.toHaveProperty('actual_avg_speed_kn')
  })
})

describe('오류', () => {
  it('서버 문구와 field를 그대로 전한다', async () => {
    const fetchMock = fakeFetch({
      '/transition': fail(422, {
        error: {
          message: '실적 연료가 입력되지 않았습니다.',
          details: [{ field: 'fuel_uses' }],
        },
      }),
    })

    await expect(
      createApiVoyageManagementProvider(fetchMock, '').transition(VOYAGE, 'COMPLETED'),
    ).rejects.toMatchObject({
      message: '실적 연료가 입력되지 않았습니다.',
      field: 'fuel_uses',
    })
  })

  it('연결 실패를 VoyageError로 감싼다', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('boom')
    }) as unknown as typeof globalThis.fetch

    await expect(
      createApiVoyageManagementProvider(fetchMock, '').saveActuals('f0a1', {
        actualDistanceNm: '1',
        actualAvgSpeedKn: '',
        actualDepartureAt: '',
        actualArrivalAt: '',
        actualFuelTon: {},
      }),
    ).rejects.toBeInstanceOf(VoyageError)
  })
})

/**
 * 운항 기록 내보내기 (#890 · `API_SPEC §8.1`).
 *
 * `PRD §5.1` MUST인데 **화면에서 도달할 수 없었다** — 서버·검사가 완비돼 있고 프론트
 * 호출부가 0건이었다. 여기서 보는 것은 **조건이 실제로 쿼리에 실리는가**와
 * **응답이 파일로 넘어가는가**다.
 */
describe('exportData — API_SPEC §8.1', () => {
  function csvResponse(disposition: string | null): Response {
    return {
      ok: true,
      status: 200,
      headers: { get: (name: string) => (name === 'Content-Disposition' ? disposition : null) },
      blob: async () => new Blob(['voyage_no\n2026-01\n'], { type: 'text/csv' }),
    } as unknown as Response
  }

  it('type·year·format을 쿼리에 싣는다', async () => {
    const fetchMock = fakeFetch({ '/export': csvResponse(null) })
    const saved: Array<[Blob, string]> = []
    const provider = createApiVoyageManagementProvider(fetchMock, '', (blob, name) =>
      saved.push([blob, name]),
    )

    await provider.exportData('v-1', 'type=voyages&format=csv&year=2026', 'voyages_2026.csv')

    const url = String((fetchMock as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0])
    expect(url).toContain('/vessels/v-1/export?')
    expect(url).toContain('type=voyages')
    expect(url).toContain('year=2026')
    expect(url).toContain('format=csv')
  })

  it('서버가 준 파일명을 그대로 쓴다 — 우리가 지어내지 않는다', async () => {
    const disposition = "attachment; filename=\"voyages_2026.csv\"; filename*=UTF-8''voyages_2026.csv"
    const fetchMock = fakeFetch({ '/export': csvResponse(disposition) })
    const saved: string[] = []
    const provider = createApiVoyageManagementProvider(fetchMock, '', (_blob, name) =>
      saved.push(name),
    )

    const name = await provider.exportData('v-1', 'type=voyages&format=csv', '대체.csv')

    expect(name).toBe('voyages_2026.csv')
    expect(saved).toEqual(['voyages_2026.csv'])
  })

  it('헤더가 없으면 대체 이름을 쓴다 — 이름 없는 파일을 내려보내지 않는다', async () => {
    const fetchMock = fakeFetch({ '/export': csvResponse(null) })
    const saved: string[] = []
    const provider = createApiVoyageManagementProvider(fetchMock, '', (_blob, name) =>
      saved.push(name),
    )

    expect(await provider.exportData('v-1', 'type=voyages&format=json', 'voyages.json')).toBe(
      'voyages.json',
    )
    expect(saved).toEqual(['voyages.json'])
  })

  it('실패 응답을 파일로 저장하지 않는다 — 오류 봉투를 화면 문구로 올린다', async () => {
    /*
     * ⚠️ 이것이 이 묶음의 핵심이다. 실패 응답은 CSV가 아니라 `§1.3.2` 오류 봉투다.
     * 그대로 저장하면 사용자는 **「받았다」고 믿고 열어서야** 오류 JSON을 본다.
     */
    const fetchMock = fakeFetch({
      '/export': fail(422, { error: { message: '지원하지 않는 형식입니다: xlsx' } }),
    })
    const saved: string[] = []
    const provider = createApiVoyageManagementProvider(fetchMock, '', (_blob, name) =>
      saved.push(name),
    )

    await expect(provider.exportData('v-1', 'type=voyages&format=xlsx', 'x.csv')).rejects.toThrow(
      '지원하지 않는 형식입니다: xlsx',
    )
    expect(saved).toEqual([])
  })

  it('연결 실패를 VoyageError로 감싼다', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('boom')
    }) as unknown as typeof globalThis.fetch

    await expect(
      createApiVoyageManagementProvider(fetchMock, '', () => {}).exportData(
        'v-1',
        'type=voyages&format=csv',
        'x.csv',
      ),
    ).rejects.toBeInstanceOf(VoyageError)
  })
})
