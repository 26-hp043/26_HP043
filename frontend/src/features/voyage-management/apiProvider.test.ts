import { describe, expect, it, vi } from 'vitest'
import { createApiVoyageManagementProvider, VoyageError } from './apiProvider'
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
  regulationYear: '2026',
  fuelType: 'HFO',
  plannedFuelTon: '210',
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
})

describe('saveActuals — API_SPEC §3.6', () => {
  const draft: ActualsDraft = {
    actualDistanceNm: '11200',
    actualAvgSpeedKn: '',
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
        actualFuelTon: {},
      }),
    ).rejects.toBeInstanceOf(VoyageError)
  })
})
