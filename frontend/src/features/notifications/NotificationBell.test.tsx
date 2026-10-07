// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { NotificationBell } from './NotificationBell'
import type { NotificationItem, NotificationSnapshot } from './types'

/**
 * 상단바 종 버튼 (#2204 · `DESIGN_SYSTEM §7.2` 「알림」).
 *
 * 개수 · 단계 글자 · 링크 · 상태 목록(펼쳐도 숫자가 줄지 않는다) · 여닫기를 본다.
 */

function item(over: Partial<NotificationItem>): NotificationItem {
  return {
    kind: 'CORRECTIVE_ACTION',
    level: 'RISK',
    vesselId: 'v1',
    vesselName: '가선',
    reason: 'E_THIS_YEAR',
    days: null,
    voyageId: null,
    voyageNo: null,
    count: null,
    ...over,
  }
}

const SNAPSHOT: NotificationSnapshot = {
  counts: { risk: 2, check: 2, total: 4 },
  items: [
    item({}),
    item({ kind: 'D_ENTRY_SOON', vesselId: 'v2', vesselName: '나선', reason: null, days: 39 }),
    item({
      kind: 'UNCONFIRMED_VOYAGE',
      level: 'CHECK',
      vesselId: 'v2',
      vesselName: '나선',
      reason: null,
      voyageId: 'y7',
      voyageNo: '2026-07',
    }),
    item({ kind: 'ESTIMATED_VALUES', level: 'CHECK', vesselId: 'v3', vesselName: '다선', reason: null, count: 2 }),
  ],
}

function renderBell(load: () => Promise<NotificationSnapshot> = async () => SNAPSHOT) {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <NotificationBell load={load} />
    </MemoryRouter>,
  )
}

const trigger = () => screen.getByTestId('notification-trigger')
const panel = () => screen.getByTestId('notification-panel')

describe('종 버튼 — 개수 (#2204)', () => {
  it('지금 걸려 있는 수를 숫자로 보이고 버튼 이름에 넣는다', async () => {
    renderBell()
    await waitFor(() => expect(trigger().textContent).toContain('4'))
    expect(trigger().getAttribute('aria-label')).toBe('알림 4건')
  })

  it('0이면 숫자를 두지 않는다', async () => {
    renderBell(async () => ({ counts: { risk: 0, check: 0, total: 0 }, items: [] }))
    await waitFor(() => expect(trigger().getAttribute('aria-label')).toBe('알림 0건'))
    expect(trigger().textContent).toBe('')
  })
})

describe('펼친 목록 — 단계 · 사실 · 링크 (#2204)', () => {
  it('처음에는 닫혀 있고, 누르면 열린다 — 두 표시가 일치한다', async () => {
    renderBell()
    expect(trigger().getAttribute('aria-expanded')).toBe('false')
    expect(panel().hidden).toBe(true)
    fireEvent.click(trigger())
    expect(trigger().getAttribute('aria-expanded')).toBe('true')
    expect(panel().hidden).toBe(false)
  })

  it('단계는 글자로 적는다 — 위험 · 확인 필요', async () => {
    renderBell()
    fireEvent.click(trigger())
    await waitFor(() => expect(within(panel()).getAllByText('위험')).toHaveLength(2))
    expect(within(panel()).getAllByText('확인 필요')).toHaveLength(2)
  })

  it('항목마다 그 화면으로 가는 링크 하나 — 해당 선박이 선택된 채로', async () => {
    renderBell()
    fireEvent.click(trigger())
    await waitFor(() => expect(within(panel()).getAllByRole('link')).toHaveLength(4))
    const hrefs = within(panel())
      .getAllByRole('link')
      .map((link) => [link.textContent, link.getAttribute('href')])
    expect(hrefs).toEqual([
      ['연간 등급 관리', '/annual-grade?vessel_id=v1'],
      ['실시간 CII', '/vessels/v2/voyages/current'],
      ['선박 상세', '/vessels/v2?actuals=y7'],
      ['데이터 점검', '/data-quality'],
    ])
  })

  it('사실 문구는 대시보드와 같은 말을 쓴다', async () => {
    renderBell()
    fireEvent.click(trigger())
    await waitFor(() =>
      expect(within(panel()).getByText('E등급 1년차 — SEEMP Part III 시정조치계획 대상')).toBeTruthy(),
    )
    expect(within(panel()).getByText('D등급 진입까지 39일')).toBeTruthy()
    expect(within(panel()).getByText('항차 2026-07 실적 확정 전')).toBeTruthy()
    expect(within(panel()).getByText('실측이 아닌 값 2건')).toBeTruthy()
  })

  it('상태 목록이다 — 펼쳐도 숫자가 줄지 않는다(읽음이 없다)', async () => {
    renderBell()
    await waitFor(() => expect(trigger().textContent).toContain('4'))
    fireEvent.click(trigger())
    fireEvent.click(trigger())
    await waitFor(() => expect(trigger().textContent).toContain('4'))
  })

  it('펼칠 때마다 다시 받는다 — 방금 해결한 것이 사라져 있어야 한다', async () => {
    const load = vi.fn(async () => SNAPSHOT)
    renderBell(load)
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1))
    fireEvent.click(trigger())
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2))
  })

  it('없으면 「없습니다」라고 적는다', async () => {
    renderBell(async () => ({ counts: { risk: 0, check: 0, total: 0 }, items: [] }))
    fireEvent.click(trigger())
    await waitFor(() => expect(within(panel()).getByText('지금 걸려 있는 알림이 없습니다')).toBeTruthy())
  })

  it('받지 못하면 목록 안에 적고 종 버튼은 남는다', async () => {
    renderBell(async () => {
      throw new Error('down')
    })
    fireEvent.click(trigger())
    await waitFor(() => expect(within(panel()).getByText('알림을 불러오지 못했습니다')).toBeTruthy())
    expect(trigger()).toBeTruthy()
  })
})

describe('여닫기 (#2204)', () => {
  it('Esc로 닫고 초점을 버튼으로 되돌린다', async () => {
    renderBell()
    fireEvent.click(trigger())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(panel().hidden).toBe(true)
    expect(document.activeElement).toBe(trigger())
  })

  it('바깥을 누르면 닫힌다', async () => {
    renderBell()
    fireEvent.click(trigger())
    fireEvent.mouseDown(document.body)
    expect(panel().hidden).toBe(true)
  })

  it('aria-controls가 실제 요소를 가리킨다 — 닫혀 있을 때도', () => {
    renderBell()
    const id = trigger().getAttribute('aria-controls')!
    expect(document.getElementById(id)).toBe(panel())
  })
})
