// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CalculationHistory } from './CalculationHistory'

/**
 * 재계산 필요 표시가 **화면에 보이는가** (#992 · `PRD §8.4`).
 *
 * `needs_recalc`는 켜지는데 보는 자리가 없었다(`#776` 정정). 규칙만 검사하면 화면이 그 값을
 * 그리지 않아도 초록이다.
 */
function run(id: string, needsRecalc: boolean) {
  return {
    calculation_run_id: id,
    calculation_type: 'VOYAGE_ESTIMATE',
    voyage_id: needsRecalc ? 'voy-1' : null,
    result_summary: { attained_cii: '5.000000', estimated_rating: 'C' },
    needs_recalc: needsRecalc,
    created_at: '2026-09-11T00:00:00Z',
  }
}

function respond(data: unknown[], meta: Record<string, unknown>) {
  return { ok: true, status: 200, json: async () => ({ data, meta }) } as Response
}

describe('계산 이력 (#992)', () => {
  it('재계산 필요 계산을 배지로 표시하고 건수를 머리에 적는다', async () => {
    const fetchImpl = vi.fn(async () =>
      respond([run('r1', true), run('r2', false)], { next_cursor: null, has_more: false }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()
    expect(screen.getAllByText('재계산 필요')).toHaveLength(1)
    expect(screen.getByText('현행')).toBeTruthy()
    // 항차에 붙은 계산(#817)은 표시가 따로 있다
    expect(screen.getByText('항차')).toBeTruthy()
  })

  it('다음 페이지를 커서로 받아 뒤에 붙인다', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(respond([run('r1', false)], { next_cursor: 'c2', has_more: true }))
      .mockResolvedValueOnce(respond([run('r2', true)], { next_cursor: null, has_more: false }))
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    fireEvent.click(await screen.findByRole('button', { name: '이전 계산 더 보기' }))
    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()
    expect(String(fetchImpl.mock.calls[1][0])).toContain('cursor=c2')
    expect(screen.getAllByText('CII 예측')).toHaveLength(2)
  })

  it('계산이 없으면 그렇다고 말한다 — 빈 표를 두지 않는다', async () => {
    const fetchImpl = vi.fn(async () => respond([], { next_cursor: null, has_more: false }))
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)
    expect(await screen.findByText('이 선박으로 실행한 계산이 없습니다.')).toBeTruthy()
  })
})
