import { describe, expect, it, vi } from 'vitest'
import { DataQualityUnavailableError, createApiDataQualityProvider } from './apiProvider'

/**
 * 데이터 점검 provider — `API_SPEC §2.16` 계약 고정 (#513).
 *
 * 핵심은 둘이다. ⑴ 수치를 **문자열 그대로** 둔다 ⑵ **모르는 심각도를 조용히 버리지 않는다** —
 * 버리면 그 건수가 화면에서 사라져 「해당 없음」으로 읽힌다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const BODY = {
  data: {
    regulation_year: 2026,
    summary: {
      substituted_count: 1,
      unavailable_count: 0,
      anomaly_count: 0,
      unconfirmed_count: 0,
      anomaly_unjudged_count: 2,
      completeness_ratio: '0.4000',
    },
    vessels: [
      {
        vessel_id: 'v1',
        vessel_name: 'MV One',
        data_available: true,
        unavailable_reason: null,
        ytd_attained_cii: '5.1234',
        ytd_rating: 'C',
        voyage_count: 2,
        completeness_ratio: '0.4000',
      },
    ],
    issues: [
      {
        severity: 'SUBSTITUTED',
        vessel_id: 'v1',
        vessel_name: 'MV One',
        voyage_id: 'voy-2',
        voyage_no: 'B',
        codes: ['FUEL:HFO'],
        cii_impact: {
          attained_cii: '5.1234',
          attained_cii_without: '4.9000',
          delta: '0.2234',
          rating: 'C',
          rating_without: 'B',
        },
        cii_impact_reason: null,
      },
    ],
  },
  meta: {},
}

describe('createApiDataQualityProvider', () => {
  it('연도를 쿼리로 싣고 응답을 화면 모양으로 바꾼다 — 수치는 문자열 그대로', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(BODY))
    const provider = createApiDataQualityProvider(fetchImpl as typeof fetch, '/api/v1')

    const snapshot = await provider.load(2026)

    expect(String(fetchImpl.mock.calls[0][0])).toBe('/api/v1/fleet/data-quality?regulation_year=2026')
    expect(snapshot.counts).toEqual({ SUBSTITUTED: 1, UNAVAILABLE: 0, ANOMALY: 0, UNCONFIRMED: 0 })
    expect(snapshot.anomalyUnjudged).toBe(2)
    expect(snapshot.completenessRatio).toBe('0.4000')
    expect(snapshot.issues[0].cii).toEqual({
      attainedCii: '5.1234',
      attainedCiiWithout: '4.9000',
      delta: '0.2234',
      rating: 'C',
      ratingWithout: 'B',
    })
  })

  it('연도를 주지 않으면 쿼리 없이 부른다 — 서버 기본(올해)을 쓴다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(BODY))
    await createApiDataQualityProvider(fetchImpl as typeof fetch, '/api/v1').load()

    expect(String(fetchImpl.mock.calls[0][0])).toBe('/api/v1/fleet/data-quality')
  })

  it('⚠️ 모르는 심각도는 버리지 않고 오류로 낸다', async () => {
    const body = structuredClone(BODY)
    body.data.issues[0].severity = 'SOMETHING_NEW'
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(body))

    await expect(
      createApiDataQualityProvider(fetchImpl as typeof fetch, '/api/v1').load(2026),
    ).rejects.toBeInstanceOf(DataQualityUnavailableError)
  })

  it('서버 오류는 상태 코드와 함께 알린다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse({}, 409))

    await expect(
      createApiDataQualityProvider(fetchImpl as typeof fetch, '/api/v1').load(2026),
    ).rejects.toThrow('HTTP 409')
  })
})
