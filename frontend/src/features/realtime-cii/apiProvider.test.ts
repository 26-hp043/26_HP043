import { describe, expect, it, vi } from 'vitest'
import { createApiRealtimeCiiProvider, RealtimeCiiError } from './apiProvider'

/**
 * 실시간 CII provider 계약 (`API_SPEC §2.14` · `#357`).
 *
 * 고정하는 것 셋.
 *
 * * **⑵에 등급이 오지 않는 것** — 서버가 실수로 실어 보내도 화면에는 오면 안 된다
 *   (`COR-1`). provider가 마지막 방벽이다.
 * * **`as_of`가 없으면 오류인 것** — 실시간 화면에서 「언제 기준 값인가」는 값
 *   자체만큼 중요하다.
 * * **수치를 문자열로 두는 것** — `parseFloat`으로 되돌리면 `API_SPEC §1.7`이
 *   지킨 정밀도가 사라진다.
 */

/**
 * 실제 서버 응답에서 가져온 형태 (2026-08-17 실측).
 *
 * 형을 좁히지 않는다 — 아래 테스트들이 **서버가 다르게 보낸 경우**를 흉내 내려면
 * 필드를 지우거나 계약에 없는 값을 넣을 수 있어야 한다. 좁은 형을 붙이면 그 변형이
 * 타입 단계에서 막혀, 정작 검증하려던 상황을 만들 수 없다.
 */
interface LooseBody {
  data: Record<string, unknown>
  meta: Record<string, unknown>
}

const OK_BODY: LooseBody = {
  data: {
    vessel_id: '00000000-0000-4000-8000-000000000002',
    vessel_name: 'STAR SKIPPER',
    regulation_year: 2026,
    transport_capacity_basis: 'DWT',
    underway_state: 'NOT_UNDER_WAY',
    ytd: {
      data_available: true,
      attained_cii: '18.637188',
      required_cii: '17.374582',
      ratio_to_required: '1.07267',
      rating: 'B',
      risk_level: 'WATCH',
      margin_ratio: '0.09321',
      total_co2_ton: '620.00',
      total_fuel_ton: '199.10',
      underway_distance_nm: '10620.00',
      not_underway_distance_nm: '0.00',
      total_distance_nm: '10620.00',
      voyage_count: 3,
      not_underway_period_count: 1,
    },
    current_voyage: {
      voyage_id: 'vy-1',
      voyage_no: '2026-02',
      status: 'IN_PROGRESS',
      departure_port_name: 'Busan',
      arrival_port_name: 'Singapore',
      planned_distance_nm: '3000.00',
      underway_hours: '112.0000',
      distance_nm: '1848.00',
      fuel_ton: '140.00',
      fuel_type: 'HFO',
      is_simulated: true,
      attained_cii: '4.720000',
      co2_ton: '435.96',
    },
    year_end_projection: {
      data_available: true,
      reason: null,
      attained_cii: '19.500000',
      required_cii: '17.374582',
      ratio_to_required: '1.12234',
      rating: 'C',
      risk_level: 'WATCH',
      assumptions: {
        method: 'YTD_DAILY_AVERAGE',
        elapsed_days: '227.73',
        remaining_days: '137.27',
        daily_distance_nm: '46.63',
        daily_fuel_ton: '0.87',
        projected_extra_distance_nm: '6400.00',
        projected_extra_fuel_ton: '120.00',
        fuel_type: 'HFO',
      },
    },
    warnings: ['REFERENCE_ONLY', 'SIMULATION_NO_FUEL_RATE'],
  },
  meta: { as_of: '2026-08-17T02:00:00+00:00', simulated: true },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const VESSEL = '00000000-0000-4000-8000-000000000002'

describe('요청', () => {
  it('선박 리소스에 건다 — 항차가 아니다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(fetchImpl.mock.calls[0][0]).toBe(`/api/v1/vessels/${VESSEL}/cii/current`)
  })
})

describe('응답 매핑', () => {
  it('3종 값을 모두 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.ytd.rating).toBe('B')
    expect(result.currentVoyage?.attainedCii).toBe('4.720000')
    expect(result.projection.rating).toBe('C')
  })

  it('항차 구간값에 등급을 올리지 않는다 — 서버가 실어 보내도 막는다', async () => {
    const withRating = structuredClone(OK_BODY)
    ;(withRating.data.current_voyage as Record<string, unknown>).rating = 'D'

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(withRating))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.currentVoyage?.rating).toBeNull()
  })

  it('수치를 문자열 그대로 둔다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.ytd.attainedCii).toBe('18.637188')
    expect(typeof result.ytd.requiredCii).toBe('string')
  })

  it('as_of와 simulated를 화면까지 올린다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.asOf).toBe('2026-08-17T02:00:00+00:00')
    expect(result.simulated).toBe(true)
  })

  it('진행 중 항차가 없으면 null이다 — 오류가 아니다', async () => {
    const body = structuredClone(OK_BODY)
    body.data.current_voyage = null

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.currentVoyage).toBeNull()
  })

  it('연말 예상을 못 낸 응답의 사유를 옮긴다', async () => {
    const body = structuredClone(OK_BODY)
    body.data.year_end_projection = { data_available: false, reason: 'NO_BASIS' }

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)

    expect(result.projection.dataAvailable).toBe(false)
    expect(result.projection.reason).toBe('NO_BASIS')
    expect(result.projection.assumptions).toBeNull()
  })
})

describe('실패 경로', () => {
  it('as_of가 없으면 오류다 — 언제 기준인지 모르는 실시간 값은 쓸 수 없다', async () => {
    const body = structuredClone(OK_BODY)
    body.meta = {}

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    await expect(createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)).rejects.toThrow(
      /기준 시각/,
    )
  })

  it('축이 없으면 단위를 지어 내지 않고 오류로 만든다', async () => {
    const body = structuredClone(OK_BODY)
    body.data.transport_capacity_basis = ''

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    await expect(createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)).rejects.toThrow(
      /축/,
    )
  })

  it('simulated가 없으면 참으로 둔다 — 잘못 감추는 쪽이 더 나쁘다', async () => {
    const body = structuredClone(OK_BODY)
    delete body.meta.simulated

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    const result = await createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)
    expect(result.simulated).toBe(true)
  })

  it('404는 notFound로 구분한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ error: {} }, 404))
    await expect(createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)).rejects.toMatchObject(
      { notFound: true },
    )
  })

  it('네트워크 실패를 삼키지 않고 원인을 보존한다', async () => {
    const cause = new TypeError('Failed to fetch')
    const fetchImpl = vi.fn().mockRejectedValue(cause)

    const promise = createApiRealtimeCiiProvider(fetchImpl).load(VESSEL)
    await expect(promise).rejects.toBeInstanceOf(RealtimeCiiError)
    await expect(promise).rejects.toMatchObject({ cause })
  })
})
