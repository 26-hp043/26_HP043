// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { FleetDashboard } from './FleetDashboard'

/**
 * 대시보드가 **서버 정렬·페이지**를 쓰는가 (#772 · `API_SPEC §2.8`).
 *
 * 규칙(정렬·자르기)은 서버 검사(`tests/test_fleet_summary.py`)가 잠근다. 여기서는 화면이
 * ⑴ 정렬을 바꾸면 첫 페이지부터 다시 묻고 ⑵ 다음 페이지를 **같은 정렬·첫 페이지의 기준 시각**
 * 으로 물어 뒤에 붙이는가를 본다 — provider만 검사하면 화면이 그것을 부르지 않아도 초록이다.
 */

function vessel(id: string, name: string) {
  return {
    vessel_id: id,
    name,
    ship_type: 'BULK_CARRIER',
    imo_number: '9100001',
    underway_state: 'UNDER_WAY',
    detail_status: 'SAILING',
    current_lat: null,
    current_lon: null,
    position_updated_at: null,
    is_cii_applicable_hint: true,
    gross_tonnage: 30000,
    data_available: true,
    ytd_attained_cii: '5.0000',
    ytd_required_cii: '5.5000',
    ytd_rating: 'B',
    risk_level: 'LOW',
    risk_reasons: [],
    days_to_d: null,
    days_to_d_reason: 'NOT_THIS_YEAR',
    unavailable_reason: null,
  }
}

function page(vessels: ReturnType<typeof vessel>[], meta: Record<string, unknown>) {
  return {
    data: {
      as_of: '2026-08-16T12:00:00+00:00',
      regulation_year: 2026,
      summary: {
        total: 3,
        under_way: 3,
        not_under_way: 0,
        unknown_state: 0,
        rating_distribution: { A: 0, B: 3, C: 0, D: 0, E: 0 },
        at_risk: 0,
        no_data: 0,
      },
      vessels,
      actions: [],
    },
    meta,
  }
}

function stubFetch() {
  const fetchImpl = vi.fn(async (input: unknown) => {
    const url = new URL(String(input), 'https://x')
    const body = url.searchParams.get('cursor')
      ? page([vessel('v3', '다선')], { next_cursor: null, has_more: false })
      : page([vessel('v1', '가선'), vessel('v2', '나선')], { next_cursor: 'c2', has_more: true })
    return { ok: true, status: 200, json: async () => body } as Response
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

/**
 * 선대 요약 호출만 고른다.
 *
 * 같은 전역 `fetch`로 **지도 자산이 있는지 묻는 `HEAD` 한 번**(`#763`)이 함께 나간다.
 * 호출 순서 번호로 집으면 그 한 번에 밀려 검사가 엉뚱한 요청을 본다 — 경로로 고른다.
 */
function urls(fetchImpl: ReturnType<typeof stubFetch>): URL[] {
  return fetchImpl.mock.calls
    .map(([u]) => new URL(String(u), 'https://x'))
    .filter((url) => url.pathname.includes('/fleet/summary'))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('선대 대시보드 — 서버 정렬·페이지 (#772)', () => {
  it('정렬을 바꾸면 그 정렬로 첫 페이지부터 다시 묻는다', async () => {
    const fetchImpl = stubFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')
    expect(urls(fetchImpl)[0].searchParams.get('sort')).toBe('risk')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(urls(fetchImpl)).toHaveLength(2))
    const second = urls(fetchImpl)[1]
    expect(second.searchParams.get('sort')).toBe('name')
    expect(second.searchParams.get('cursor')).toBeNull()
  })

  it('다음 페이지를 같은 정렬·첫 페이지의 기준 시각으로 물어 뒤에 붙인다', async () => {
    const fetchImpl = stubFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    const more = await screen.findByRole('button', { name: /다음 선박 불러오기/ })
    // 선대 전체 3척 중 2척만 받았다는 사실을 버튼이 말한다
    expect(more.textContent).toContain('전체 3척 중 2척')
    fireEvent.click(more)

    expect(await screen.findByText('다선')).toBeTruthy()
    const next = urls(fetchImpl)[1]
    expect(next.searchParams.get('cursor')).toBe('c2')
    expect(next.searchParams.get('sort')).toBe('risk')
    expect(next.searchParams.get('as_of')).toBe('2026-08-16T12:00:00+00:00')
    // 앞 페이지 선박이 남아 있다 — 갈아 끼우지 않고 붙인다
    expect(screen.getByText('가선')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /다음 선박 불러오기/ })).toBeNull()
  })
})
