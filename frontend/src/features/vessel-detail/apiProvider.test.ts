import { describe, expect, it, vi } from 'vitest'
import { VesselDetailError, createApiVesselDetailProvider } from './apiProvider'

/**
 * 선박 상세 provider 계약 — `API_SPEC §2.2` · `§2.7`.
 *
 * 이 화면에서 틀리면 가장 비싼 것은 **단위**다. `DESIGN_SYSTEM §4.1`이 고정 문자열을
 * 금지한 이유가 「크루즈선에 `DWT`가 표시돼도 화면이 깨지지 않아 발견이 늦다」이므로,
 * 축(`transport_capacity_basis`)을 못 받으면 **그리지 않고 실패**하는 것을 고정한다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const VESSEL_BODY = {
  data: {
    id: 'v1',
    name: 'MV Test',
    imo_number: '9100001',
    ship_type: 'BULK_CARRIER',
    deadweight: 50000,
    gross_tonnage: 30000,
    reference_speed_kn: 12,
    reference_daily_foc_ton: 20,
    default_fuel_type: 'HFO',
    underway_state: 'UNDER_WAY',
    detail_status: 'SAILING',
    current_lat: 35.1,
    current_lon: 129.04,
    position_updated_at: '2026-08-16T11:00:00+00:00',
  },
}

const HISTORY_BODY = {
  data: {
    vessel_id: 'v1',
    from: 2024,
    to: 2026,
    transport_capacity_basis: 'DWT',
    years: [
      {
        regulation_year: 2025,
        status: 'CONFIRMED',
        data_available: true,
        reason: null,
        attained_cii: '18.063633',
        required_cii: '17.765022',
        rating: 'C',
        voyage_count: 1,
        total_distance_nm: '915.00',
        total_fuel_ton: '34.00',
      },
      {
        regulation_year: 2026,
        status: 'IN_PROGRESS',
        data_available: true,
        reason: null,
        attained_cii: '21.782215',
        required_cii: '17.374582',
        rating: 'E',
        voyage_count: 1,
        total_distance_nm: '1130.00',
        total_fuel_ton: '48.00',
      },
    ],
  },
  meta: { as_of: '2026-08-16T12:00:00+00:00' },
}

/** 경로별로 다른 응답을 주는 fetch 대역. */
function routed(vessel: unknown = VESSEL_BODY, history: unknown = HISTORY_BODY) {
  return vi.fn((url: string) =>
    Promise.resolve(
      String(url).includes('cii-history')
        ? jsonResponse(history)
        : jsonResponse(vessel),
    ),
  )
}

describe('정상 응답', () => {
  it('두 응답을 하나의 화면 모델로 합친다', async () => {
    const snapshot = await createApiVesselDetailProvider(routed() as never).load('v1')

    expect(snapshot.vessel).toMatchObject({
      id: 'v1',
      name: 'MV Test',
      imoNumber: '9100001',
      underwayState: 'UNDER_WAY',
    })
    expect(snapshot.years).toHaveLength(2)
    expect(snapshot.asOf).toBe('2026-08-16T12:00:00+00:00')
  })

  it('두 호출을 병렬로 한다', async () => {
    const fetchImpl = routed()
    await createApiVesselDetailProvider(fetchImpl as never).load('v1')

    expect(fetchImpl).toHaveBeenCalledTimes(2)
    const urls = fetchImpl.mock.calls.map((c) => String(c[0]))
    expect(urls).toContain('/api/v1/vessels/v1')
    expect(urls).toContain('/api/v1/vessels/v1/cii-history')
  })

  it('CII 값을 문자열 그대로 둔다 — 되돌리면 정밀도가 사라진다', async () => {
    const snapshot = await createApiVesselDetailProvider(routed() as never).load('v1')

    expect(snapshot.years[0].attainedCii).toBe('18.063633')
    expect(typeof snapshot.years[0].attainedCii).toBe('string')
  })

  it('제원이 숫자로 와도 문자열로 통일한다', async () => {
    const snapshot = await createApiVesselDetailProvider(routed() as never).load('v1')

    expect(snapshot.vessel.deadweight).toBe('50000')
    expect(snapshot.vessel.lat).toBe('35.1')
  })

  it('진행 중 연도를 상태로 구분한다', async () => {
    const snapshot = await createApiVesselDetailProvider(routed() as never).load('v1')

    expect(snapshot.years[0].status).toBe('CONFIRMED')
    expect(snapshot.years[1].status).toBe('IN_PROGRESS')
  })
})

describe('표시 단위의 축', () => {
  it('서버가 준 축을 그대로 쓴다', async () => {
    const snapshot = await createApiVesselDetailProvider(routed() as never).load('v1')
    expect(snapshot.capacityBasis).toBe('DWT')
  })

  it('GT 축 선박을 GT로 받는다', async () => {
    const gt = structuredClone(HISTORY_BODY)
    gt.data.transport_capacity_basis = 'GT'
    const snapshot = await createApiVesselDetailProvider(
      routed(VESSEL_BODY, gt) as never,
    ).load('v1')

    expect(snapshot.capacityBasis).toBe('GT')
  })

  it('축이 없으면 그리지 않고 실패한다', async () => {
    /*
     * 임의로 DWT를 채우면 크루즈선에 DWT가 표시되는데 **화면은 깨지지 않는다.**
     * `DESIGN_SYSTEM §4.1`이 고정 문자열을 금지한 이유가 이것이다.
     */
    const broken = structuredClone(HISTORY_BODY)
    delete (broken.data as { transport_capacity_basis?: string })
      .transport_capacity_basis

    await expect(
      createApiVesselDetailProvider(routed(VESSEL_BODY, broken) as never).load('v1'),
    ).rejects.toThrow(/표시 단위의 축/)
  })

  it('알 수 없는 축도 거부한다', async () => {
    const weird = structuredClone(HISTORY_BODY)
    weird.data.transport_capacity_basis = 'TEU'

    await expect(
      createApiVesselDetailProvider(routed(VESSEL_BODY, weird) as never).load('v1'),
    ).rejects.toThrow(/표시 단위의 축/)
  })
})

describe('실패 경로', () => {
  it('404는 「없는 선박」으로 구분한다', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse({}, 404)))
    const promise = createApiVesselDetailProvider(fetchImpl as never).load('nope')

    await expect(promise).rejects.toThrow(VesselDetailError)
    await expect(promise).rejects.toMatchObject({ notFound: true })
  })

  it('네트워크 실패를 삼키지 않는다', async () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    await expect(
      createApiVesselDetailProvider(fetchImpl as never).load('v1'),
    ).rejects.toThrow(/연결하지 못했습니다/)
  })

  it('5xx는 상태 코드를 남긴다', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse({}, 500)))
    await expect(
      createApiVesselDetailProvider(fetchImpl as never).load('v1'),
    ).rejects.toThrow(/500/)
  })
})
