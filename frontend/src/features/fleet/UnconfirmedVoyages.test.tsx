// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { UnconfirmedVoyages } from './UnconfirmedVoyages'
import type { DataQualityIssue, DataQualityProvider, DataQualitySnapshot } from '../data-quality/types'

/**
 * 대시보드의 「실적 확정 전 항차」 카드 (#1573).
 *
 * 규칙(`unconfirmedVoyages`)은 `fleetRules.test.ts`가 본다. 여기서는 **화면이 그 목록을 입구로
 * 그리는가** — 경로 · 5건 제한 · 0건 · 실패를 본다.
 */
function issue(i: number, over: Partial<DataQualityIssue> = {}): DataQualityIssue {
  return {
    severity: 'UNCONFIRMED',
    vesselId: `v${i}`,
    vesselName: `선박${i}`,
    voyageId: `voy-${i}`,
    voyageNo: `2026-0${i}`,
    codes: ['STATUS_COMPLETED'],
    cii: null,
    ciiReason: null,
    ...over,
  }
}

function snapshot(issues: DataQualityIssue[]): DataQualitySnapshot {
  return {
    regulationYear: 2026,
    counts: { SUBSTITUTED: 0, UNAVAILABLE: 0, ANOMALY: 0, UNCONFIRMED: issues.length },
    anomalyUnjudged: 0,
    completenessRatio: null,
    vessels: [],
    issues,
  }
}

function renderWith(provider: DataQualityProvider) {
  return render(
    <MemoryRouter>
      <UnconfirmedVoyages provider={provider} />
    </MemoryRouter>,
  )
}

describe('실적 확정 전 항차 카드 (#1573)', () => {
  it('건수와 행마다 그 항차로 가는 입구 — 실적 입력이 열린 채 도착하는 경로다', async () => {
    renderWith({ load: vi.fn(async () => snapshot([issue(1), issue(2)])) })
    const card = await screen.findByRole('region', { name: '실적 확정 전 항차' })
    expect(within(card).getByRole('heading').textContent).toContain('2건')
    const link = within(card).getByRole('link', { name: '이 항차로 — 선박1 2026-01' })
    expect(link.getAttribute('href')).toBe('/vessels/v1?actuals=voy-1')
  })

  it('다른 심각도와 선박 단위 행은 할 일이 아니다', async () => {
    renderWith({
      load: vi.fn(async () =>
        snapshot([issue(1), issue(2, { severity: 'ANOMALY' }), issue(3, { voyageId: null })]),
      ),
    })
    const card = await screen.findByRole('region', { name: '실적 확정 전 항차' })
    expect(within(card).getAllByRole('link', { name: /^이 항차로/ })).toHaveLength(1)
  })

  it('5건까지 보이고 나머지는 데이터 점검으로 넘긴다', async () => {
    renderWith({ load: vi.fn(async () => snapshot([1, 2, 3, 4, 5, 6, 7].map((i) => issue(i)))) })
    const card = await screen.findByRole('region', { name: '실적 확정 전 항차' })
    expect(within(card).getAllByRole('link', { name: /^이 항차로/ })).toHaveLength(5)
    expect(within(card).getByText(/2건 더/)).toBeTruthy()
    expect(within(card).getByRole('link', { name: /데이터 점검에서 모두 보기/ }).getAttribute('href')).toBe(
      '/data-quality',
    )
  })

  it('5건 이하면 「더」가 없다', async () => {
    renderWith({ load: vi.fn(async () => snapshot([1, 2, 3, 4, 5].map((i) => issue(i)))) })
    const card = await screen.findByRole('region', { name: '실적 확정 전 항차' })
    expect(within(card).queryByText(/건 더/)).toBeNull()
  })

  it('0건이면 카드를 그리지 않는다', async () => {
    const load = vi.fn(async () => snapshot([issue(1, { severity: 'SUBSTITUTED' })]))
    const { container } = renderWith({ load })
    await waitFor(() => expect(load).toHaveBeenCalled())
    await Promise.resolve()
    expect(screen.queryByRole('region', { name: '실적 확정 전 항차' })).toBeNull()
    expect(container.textContent).toBe('')
  })

  it('조회에 실패하면 0건과 섞지 않고 한 줄로 말한다', async () => {
    renderWith({
      load: vi.fn(async () => {
        throw new Error('x')
      }),
    })
    expect(await screen.findByText(/실적 확정 전 항차를 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /데이터 점검에서 보기/ })).toBeTruthy()
  })
})
