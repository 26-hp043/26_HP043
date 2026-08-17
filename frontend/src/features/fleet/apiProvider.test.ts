import { describe, expect, it, vi } from 'vitest'
import { FleetUnavailableError, createApiFleetProvider } from './apiProvider'

/**
 * 선대 요약 provider 테스트 — `API_SPEC §2.8` 계약 고정.
 *
 * 서버가 다른 형태를 내려주면 여기서 잡힌다. 특히 **수치를 문자열로 유지하는 것**과
 * 「선박 0척(정상)」·「불러오지 못함(오류)」을 구분하는 것이 계약의 핵심이다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const OK_BODY = {
  data: {
    as_of: '2026-08-16T12:00:00+00:00',
    regulation_year: 2026,
    summary: {
      total: 2,
      under_way: 1,
      not_under_way: 0,
      unknown_state: 1,
      rating_distribution: { A: 0, B: 0, C: 1, D: 0, E: 1 },
      at_risk: 1,
      no_data: 0,
    },
    vessels: [
      {
        vessel_id: 'v1',
        name: 'MV Risk',
        ship_type: 'BULK_CARRIER',
        imo_number: '9100001',
        underway_state: 'UNDER_WAY',
        detail_status: 'SAILING',
        current_lat: '35.100000',
        current_lon: '129.040000',
        position_updated_at: '2026-08-16T11:00:00+00:00',
        data_available: true,
        ytd_attained_cii: '9.4200',
        ytd_required_cii: '5.0450',
        ytd_rating: 'E',
        risk_level: 'CRITICAL',
        risk_reasons: ['E_THIS_YEAR'],
        days_to_d: null,
        days_to_d_reason: 'ALREADY_AT_OR_BELOW',
      },
      {
        vessel_id: 'v2',
        name: 'MV Plain',
        ship_type: 'BULK_CARRIER',
        imo_number: '9100002',
        underway_state: null,
        detail_status: null,
        current_lat: null,
        current_lon: null,
        position_updated_at: null,
        data_available: true,
        ytd_attained_cii: '5.0000',
        ytd_required_cii: '5.0450',
        ytd_rating: 'C',
        risk_level: 'MEDIUM',
        risk_reasons: [],
        days_to_d: 42,
        days_to_d_reason: null,
      },
      {
        // 제원이 비어 계산하지 못한 선박 (#419) — 목록에 남고 사유가 따라온다.
        vessel_id: 'v3',
        name: 'MV NoSpec',
        ship_type: 'BULK_CARRIER',
        imo_number: '9100003',
        underway_state: null,
        detail_status: null,
        current_lat: null,
        current_lon: null,
        position_updated_at: null,
        data_available: false,
        unavailable_reason: 'MISSING_SPEC',
        ytd_attained_cii: null,
        ytd_required_cii: null,
        ytd_rating: null,
        risk_level: null,
        risk_reasons: [],
        days_to_d: null,
        days_to_d_reason: 'NO_DATA',
      },
    ],
    actions: [
      {
        vessel_id: 'v1',
        vessel_name: 'MV Risk',
        severity: 'critical',
        reason: 'E_THIS_YEAR',
        message: 'E등급 1년차 — SEEMP Part III 시정조치계획 대상',
      },
    ],
  },
}

describe('정상 응답', () => {
  it('snake_case 응답을 화면 타입으로 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    expect(snapshot.asOf).toBe('2026-08-16T12:00:00+00:00')
    expect(snapshot.regulationYear).toBe(2026)
    expect(snapshot.vessels[0]).toMatchObject({
      id: 'v1',
      underwayState: 'UNDER_WAY',
      ytdRating: 'E',
      riskLevel: 'CRITICAL',
      riskReasons: ['E_THIS_YEAR'],
      daysToDReason: 'ALREADY_AT_OR_BELOW',
    })
    expect(snapshot.actions[0]).toMatchObject({ vesselId: 'v1', reason: 'E_THIS_YEAR' })
  })

  it('서버 집계를 그대로 쓴다 — 화면이 다시 세지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    expect(snapshot.counts).toMatchObject({
      total: 2,
      underWay: 1,
      unknownState: 1,
      atRisk: 1,
    })
  })

  it('수치를 문자열 그대로 둔다 — 되돌리면 API_SPEC §1.7의 정밀도가 사라진다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    expect(snapshot.vessels[0].ytdAttainedCii).toBe('9.4200')
    expect(typeof snapshot.vessels[0].ytdAttainedCii).toBe('string')
  })

  it('상태·좌표가 없는 선박도 목록에 남는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    // 좌표가 없다고 목록에서 빼면 사용자가 「배가 사라졌다」고 읽는다.
    expect(snapshot.vessels[1]).toMatchObject({
      id: 'v2',
      underwayState: null,
      lat: null,
      lon: null,
    })
  })

  it('계산하지 못한 선박도 목록에 남고 사유가 따라온다 (#419)', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    // 제원이 없는 한 척 때문에 선대 전체가 사라지던 것이 이 이슈였다.
    expect(snapshot.vessels).toHaveLength(3)
    expect(snapshot.vessels[2]).toMatchObject({
      id: 'v3',
      dataAvailable: false,
      unavailableReason: 'MISSING_SPEC',
      ytdRating: null,
    })
  })

  it('값이 있는 선박의 사유는 null이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    // 서버가 필드를 싣지 않아도 undefined가 화면까지 새어 나가면 안 된다.
    expect(snapshot.vessels[0].unavailableReason).toBeNull()
  })

  it('모르는 사유는 null로 떨어뜨린다 — 틀린 안내보다 안내 없음이 낫다', async () => {
    const body = structuredClone(OK_BODY)
    body.data.vessels[2].unavailable_reason = 'SOMETHING_NEW'
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    // 그대로 통과시키면 문구 함수의 기본 분기가 「항차를 등록하세요」를 출력한다.
    expect(snapshot.vessels[2].unavailableReason).toBeNull()
  })

  it('알 수 없는 underway_state는 null로 떨어뜨린다', async () => {
    const body = structuredClone(OK_BODY)
    body.data.vessels[0].underway_state = 'WARP_SPEED'
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    expect(snapshot.vessels[0].underwayState).toBeNull()
  })

  it('선박 0척은 오류가 아니다 — 정상 응답으로 받는다', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ data: { as_of: '2026-08-16T12:00:00Z' } }))
    const snapshot = await createApiFleetProvider(fetchImpl).load()

    expect(snapshot.vessels).toEqual([])
    expect(snapshot.counts.total).toBe(0)
    expect(snapshot.counts.ratingDistribution).toEqual({ A: 0, B: 0, C: 0, D: 0, E: 0 })
  })

  it('올바른 경로를 호출한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    await createApiFleetProvider(fetchImpl).load()

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/v1/fleet/summary',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    )
  })
})

describe('실패 경로', () => {
  it('네트워크 실패를 삼키지 않는다', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(createApiFleetProvider(fetchImpl).load()).rejects.toThrow(
      FleetUnavailableError,
    )
  })

  it('5xx는 상태 코드를 남긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 503))
    await expect(createApiFleetProvider(fetchImpl).load()).rejects.toThrow(/503/)
  })

  it('as_of가 없으면 형식 오류다 — 기준 시각 없이는 화면을 그릴 수 없다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: { vessels: [] } }))
    await expect(createApiFleetProvider(fetchImpl).load()).rejects.toThrow(
      /응답 형식이 올바르지 않습니다/,
    )
  })
})
