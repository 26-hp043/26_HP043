import { describe, expect, it, vi } from 'vitest'
import { fetchCalculationPage, toCalculationRow } from './calculationRuns'

/**
 * 계산 이력 규칙 (#992 · `API_SPEC §1.9`).
 */
describe('toCalculationRow', () => {
  it('기능① 요약은 소수 3자리 · 종류는 화면 이름으로', () => {
    const row = toCalculationRow({
      calculation_run_id: 'r1',
      calculation_type: 'VOYAGE_ESTIMATE',
      voyage_id: 'voy-1',
      result_summary: { attained_cii: '4.982400', estimated_rating: 'C' },
      needs_recalc: true,
      created_at: '2026-09-11T00:00:00Z',
    })
    expect(row.typeLabel).toBe('CII 예측')
    expect(row.ciiText).toBe('4.982')
    expect(row.rating).toBe('C')
    expect(row.attachedToVoyage).toBe(true)
    expect(row.needsRecalc).toBe(true)
  })

  it('요약이 없는 종류(항로 비교·연간)는 값 자리를 「—」로 — 빈칸은 「못 불러왔다」로 읽힌다', () => {
    const row = toCalculationRow({
      calculation_run_id: 'r2',
      calculation_type: 'ANNUAL_MONTE_CARLO',
      voyage_id: null,
      result_summary: {},
      needs_recalc: false,
      created_at: '2026-09-11T00:00:00Z',
    })
    expect(row.typeLabel).toBe('연간 시뮬레이션')
    expect(row.ciiText).toBe('—')
    expect(row.rating).toBeNull()
    expect(row.attachedToVoyage).toBe(false)
  })
})

describe('fetchCalculationPage', () => {
  it('그 선박의 최신 20건을 커서와 함께 묻고 페이지 정보를 meta에서 읽는다', async () => {
    const fetchImpl = vi.fn(
      async () =>
        ({
          ok: true,
          status: 200,
          json: async () => ({ data: [], meta: { next_cursor: 'c2', has_more: true } }),
        }) as Response,
    )
    const page = await fetchCalculationPage('v 1', 'c1', fetchImpl as unknown as typeof fetch, '/api/v1')
    const url = new URL(String((fetchImpl.mock.calls[0] as unknown as [string])[0]), 'https://x')
    expect(url.pathname).toBe('/api/v1/calculations')
    expect(url.searchParams.get('vessel_id')).toBe('v 1')
    expect(url.searchParams.get('limit')).toBe('20')
    expect(url.searchParams.get('cursor')).toBe('c1')
    expect(page).toEqual({ rows: [], nextCursor: 'c2', hasMore: true })
  })

  it('data가 배열이 아니면 던진다 — 「계산이 없다」로 삼키지 않는다', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ data: {} }) }) as Response)
    await expect(
      fetchCalculationPage('v', null, fetchImpl as unknown as typeof fetch, '/api/v1'),
    ).rejects.toThrow()
  })
})
