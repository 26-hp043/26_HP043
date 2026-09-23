// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { FleetDashboard } from './FleetDashboard'
import { regulationParametersPath } from '../parameters/referenceRules'

/*
 * #1824 — 지도 위 패널은 **1100 이하에서 접힌 채로 시작한다**. jsdom의 기본 폭은
 * `1024`라 그냥 두면 목록·조치가 접힌 채로 그려져, 선대 데이터를 보는 아래 검사들이
 * 전부 **패널 접힘 때문에** 실패한다. 이 파일이 보는 것은 데이터 동작이므로 넓은
 * 화면을 선언한다 — 접힘 규칙 자체는 `panelState.test.ts`가 따로 잠근다.
 */
beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true })
  try {
    window.localStorage.removeItem('bluelog.fleet.panelOpen')
  } catch {
    // 저장이 없는 환경이면 폭만으로 정해진다.
  }
})

/**
 * 지도는 대역으로 둔다 (`#1091`).
 *
 * `FleetDashboard`는 `FleetMap`을 `lazy()`로 불러오고, 그 안의 `maplibre-gl`이
 * 마운트되는 순간 **WebGL2 컨텍스트를 요구한다.** jsdom에는 그것이 없어
 * `GPUInitializationError`가 **테스트 밖에서(uncaught)** 던져진다 — 단언은 전부
 * 통과하는데 러너가 `Errors 2`로 실패한다(CI `frontend` 잡에서 실측).
 *
 * 종전에 드러나지 않은 이유는 **lazy chunk가 풀리기 전에 검사가 끝났기 때문**이다.
 * 기다리는 검사를 하나 더 넣자 chunk가 먼저 풀려 지도가 실제로 마운트됐다 — 즉
 * 종전 초록은 **타이밍에 기댄 것**이었다.
 *
 * 이 파일의 어느 검사도 지도를 단언하지 않는다(목록·정렬·페이지·링크·문구만 본다).
 * 지도 자체는 자산 유무를 묻는 `HEAD` 요청(`#763`)과 함께 별도로 다룬다.
 */
vi.mock('./FleetMap', () => ({ FleetMap: () => null }))

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
    risk_reasons: [] as string[],
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

describe('데이터 점검 진입 (#1082 · `UIFLOW 2-11`)', () => {
  it('조치 항목이 있으면 조치 카드에 「데이터 점검」 링크가 있다', async () => {
    const body = page([vessel('v1', '가선')], { next_cursor: null, has_more: false })
    body.data.actions = [
      { vessel_id: 'v1', vessel_name: '가선', reason: 'RATING_D', severity: 'warning', message: 'D등급' },
    ] as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    const card = await screen.findByLabelText('조치 필요')
    const link = within(card).getByRole('link', { name: '데이터 점검' })
    expect(link.getAttribute('href')).toBe('/data-quality')
  })
})


describe('「D등급까지」 사유 (#1091 · `API_SPEC §2.8`)', () => {
  /**
   * 규칙은 `fleetRules.test.ts`·`daysReason.sync.test.ts`가 잠근다. 여기서는 **화면이
   * 그 규칙을 실제로 부르는가**를 본다 — 규칙만 검사하면 목록이 옛 문구를 직접 적어도
   * 초록이다(`#592`가 같은 자리에서 겪은 일이다).
   */
  it.each([
    ['NOT_WORSENING', '이대로면 진입 없음'],
    ['NO_RECENT_DATA', '최근 항해 없음'],
  ])('실적이 있는 선박에 「실적 없음」을 붙이지 않는다 — %s', async (reason, expected) => {
    const row = { ...vessel('v1', '가선'), days_to_d_reason: reason }
    const body = page([row], { next_cursor: null, has_more: false })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    expect(await screen.findByText(expected)).toBeTruthy()
    expect(screen.queryByText('실적 없음')).toBeNull()
  })
})

/** 선대 요약 응답을 **손으로 푸는** fetch — 경합(`#1092`)·실패 뒤 복구(`#1814`) 검사가 함께 쓴다. */
type Deferred = { resolve: (r: Response) => void }
function deferredFetch() {
  const pending: Array<{ url: URL; d: Deferred }> = []
  // 선대 요약만 손으로 푼다 — 지도 자산 확인(`hasBasemap`) 같은 다른 fetch는 바로 404다.
  const fetchImpl = vi.fn((input: unknown) => {
    const url = new URL(String(input), 'https://x')
    if (!url.pathname.includes('/fleet/summary')) {
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) } as Response)
    }
    return new Promise<Response>((resolve) => {
      pending.push({ url, d: { resolve } })
    })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return { pending, ok: (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response }
}
const first = () => page([vessel('v1', '가선'), vessel('v2', '나선')], { next_cursor: 'c2', has_more: true })

/**
 * 정렬 변경 × 「다음 선박 불러오기」 경합과 추가 조회 실패 (`#1092`).
 *
 * 응답을 **손으로 풀어** 순서를 정한다 — ⓐ 옛 목록이 보이는 동안 버튼이 잠기는가,
 * ⓑ 늦게 온 옛 정렬 2페이지를 버리는가, ⓒ 추가 조회 실패가 받은 목록을 지우지 않는가.
 */
describe('정렬 변경 · 추가 조회 경합 (#1092)', () => {
  it('ⓐ 정렬을 바꿔 첫 페이지를 다시 받는 동안 「다음 선박」이 잠긴다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    const more = (await screen.findByRole('button', { name: /다음 선박 불러오기/ })) as HTMLButtonElement
    expect(more.disabled).toBe(false)

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(2))
    // 옛 목록은 그대로 보이지만 버튼은 잠긴다 — 옛 커서를 새 정렬에 보내면 422다
    const locked = screen.getByRole('button', { name: /정렬을 바꾸는 중/ }) as HTMLButtonElement
    expect(locked.disabled).toBe(true)
    fireEvent.click(locked)
    expect(pending).toHaveLength(2)

    await act(async () => pending[1].d.resolve(ok(first())))
    await screen.findByRole('button', { name: /다음 선박 불러오기/ })
  })

  it('ⓑ 추가 조회 중 정렬을 바꾸면 늦게 온 옛 정렬 2페이지를 버린다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    fireEvent.click(await screen.findByRole('button', { name: /다음 선박 불러오기/ }))
    await waitFor(() => expect(pending).toHaveLength(2))
    expect(pending[1].url.searchParams.get('cursor')).toBe('c2')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(3))
    // 새 정렬 1페이지가 먼저, 옛 정렬 2페이지가 늦게 온다
    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v9', '라선')], { next_cursor: 'n2', has_more: true }))),
    )
    await act(async () =>
      pending[1].d.resolve(ok(page([vessel('v3', '다선')], { next_cursor: null, has_more: false }))),
    )
    expect(screen.getByText('라선')).toBeTruthy()
    expect(screen.queryByText('다선')).toBeNull()
    // 커서도 새 정렬 것이다 — 버튼이 남아 있고 다음 요청에 n2를 보낸다
    fireEvent.click(await screen.findByRole('button', { name: /다음 선박 불러오기/ }))
    await waitFor(() => expect(pending).toHaveLength(4))
    expect(pending[3].url.searchParams.get('cursor')).toBe('n2')
    expect(pending[3].url.searchParams.get('sort')).toBe('name')
  })

  it('ⓒ 추가 조회가 실패해도 받은 목록·KPI는 남고, 아래에 오류와 「다시 시도」가 생긴다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    fireEvent.click(await screen.findByRole('button', { name: /다음 선박 불러오기/ }))
    await waitFor(() => expect(pending).toHaveLength(2))
    await act(async () =>
      pending[1].d.resolve({ ok: false, status: 503, json: async () => ({ error: { message: '잠시 뒤' } }) } as Response),
    )
    expect(await screen.findByText(/다음 선박을 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.getByText('가선')).toBeTruthy()
    expect(screen.getByText('나선')).toBeTruthy()
    const retry = screen.getByRole('button', { name: /다시 시도/ })
    fireEvent.click(retry)
    await waitFor(() => expect(pending).toHaveLength(3))
    expect(pending[2].url.searchParams.get('cursor')).toBe('c2')
    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v3', '다선')], { next_cursor: null, has_more: false }))),
    )
    expect(await screen.findByText('다선')).toBeTruthy()
    expect(screen.queryByText(/다음 선박을 불러오지 못했습니다/)).toBeNull()
  })
})

/**
 * 정렬 변경 실패 뒤의 복구 (`#1814`).
 *
 * 종전에는 실패 상태를 성공 경로가 지우지 않아 **한 번 실패하면 이후 성공해도 화면 전체가
 * 오류로 남았다.** 여기서는 ⑴ 실패가 받아 둔 목록·요약을 지우지 않고 **목록 자리**에서만
 * 알리는가 ⑵ 「다시 시도」가 같은 정렬로 첫 페이지를 다시 묻고, 성공하면 오류가 걷히고 새
 * 목록이 서는가를 본다. 오류 문구는 표시 문구라 리터럴로 단언하지 않는다(`AGENTS §4.6`).
 */
describe('정렬 실패 뒤 복구 (#1814)', () => {
  const failed = () =>
    ({ ok: false, status: 503, json: async () => ({ error: { message: '잠시 뒤' } }) }) as Response

  it('정렬이 실패해도 받아 둔 목록·요약은 남고, 다음 정렬이 성공하면 오류가 걷힌다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    await screen.findByText('가선')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(2))
    await act(async () => pending[1].d.resolve(failed()))

    // 오류는 목록 자리 안에 있고, 요약 띠와 옛 목록은 그대로다 — 화면 전체가 오류가 아니다
    const list = screen.getByRole('region', { name: '선박 목록' })
    const alert = await within(list).findByRole('alert')
    expect(screen.getByRole('region', { name: '선대 요약' })).toBeTruthy()
    expect(screen.getByText('가선')).toBeTruthy()
    expect(screen.getByText('나선')).toBeTruthy()
    // 옛 정렬의 커서를 새 정렬에 보내지 않도록 「다음 선박」은 서지 않는다 — 척수 안내는 남는다
    expect(screen.queryByRole('button', { name: /다음 선박 불러오기/ })).toBeNull()
    expect(within(list).getByText(/전체 3척 중 2척/)).toBeTruthy()

    // 「다시 시도」는 같은 정렬로 첫 페이지부터 다시 묻는다
    // 정본 문구 (PRD §6.4) — 바꾸려면 PRD 개정이 먼저다.
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(pending).toHaveLength(3))
    expect(pending[2].url.searchParams.get('sort')).toBe('name')
    expect(pending[2].url.searchParams.get('cursor')).toBeNull()
    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v9', '라선')], { next_cursor: null, has_more: false }))),
    )

    // 성공이 앞선 실패를 지운다 — 새 목록이 서고 오류는 없다
    expect(await screen.findByText('라선')).toBeTruthy()
    expect(screen.queryByText('가선')).toBeNull()
    expect(within(screen.getByRole('region', { name: '선박 목록' })).queryByRole('alert')).toBeNull()
    expect(screen.getByRole('region', { name: '선대 요약' })).toBeTruthy()
  })

  /** 셀렉트 옵션의 라벨 — 안내 문구와 **같은 출처**인지 보려고 화면에서 읽는다(하드코딩하지 않는다). */
  function optionLabel(value: string): string {
    const select = screen.getByTestId('fleet-sort') as HTMLSelectElement
    const option = Array.from(select.options).find((o) => o.value === value)
    if (!option) throw new Error(`정렬 옵션 ${value}이 없다`)
    return option.textContent ?? ''
  }

  it('실패 안내는 목록이 어느 정렬 그대로인지 말한다 — 셀렉트는 새 값을 가리키므로', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    await screen.findByText('가선')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(2))
    await act(async () => pending[1].d.resolve(failed()))

    const alert = await within(screen.getByRole('region', { name: '선박 목록' })).findByRole('alert')
    const text = alert.textContent ?? ''
    // 목록에 실제로 적용된 정렬(처음 값 risk)의 라벨이 있고, 실패한 새 정렬의 라벨은 없다
    expect(text).toContain(optionLabel('risk'))
    expect(text).not.toContain(optionLabel('name'))
    // 서버가 준 사유도 함께 있다
    expect(text).toContain('잠시 뒤')
    // 셀렉트는 사용자가 고른 값 그대로다
    expect((screen.getByTestId('fleet-sort') as HTMLSelectElement).value).toBe('name')
  })

  it('재시도 중에는 진행 표시가 서고 「다시 시도」를 다시 누를 수 없다 — 요청이 겹치지 않는다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    await screen.findByText('가선')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(2))
    await act(async () => pending[1].d.resolve(failed()))
    const list = screen.getByRole('region', { name: '선박 목록' })
    const alert = await within(list).findByRole('alert')
    // 정본 문구 (PRD §6.4) — 바꾸려면 PRD 개정이 먼저다.
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(pending).toHaveLength(3))

    // 응답 전 — 오류 대신 진행 중 표시, 「다시 시도」 없음, 옛 목록은 그대로
    expect(within(list).getByRole('status')).toBeTruthy()
    expect(within(list).queryByRole('alert')).toBeNull()
    expect(within(list).queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.getByText('가선')).toBeTruthy()
    // 다시 누를 버튼이 없으므로 요청 수가 늘지 않는다
    expect(pending).toHaveLength(3)

    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v9', '라선')], { next_cursor: null, has_more: false }))),
    )
    expect(await screen.findByText('라선')).toBeTruthy()
    expect(within(list).queryByRole('status')).toBeNull()
    expect(within(list).queryByRole('alert')).toBeNull()
  })

  it('실패 뒤 정렬을 다시 바꿔 성공해도 오류가 걷힌다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(ok(first())))
    await screen.findByText('가선')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(pending).toHaveLength(2))
    await act(async () => pending[1].d.resolve(failed()))
    await within(screen.getByRole('region', { name: '선박 목록' })).findByRole('alert')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'grade' } })
    await waitFor(() => expect(pending).toHaveLength(3))
    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v9', '라선')], { next_cursor: null, has_more: false }))),
    )

    expect(await screen.findByText('라선')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: '선박 목록' })).queryByRole('alert')).toBeNull()
    expect(screen.getByRole('region', { name: '선대 요약' })).toBeTruthy()
  })

  it('받아 둔 목록이 없는 첫 조회 실패는 그대로 화면 전체의 오류다', async () => {
    const { pending } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(failed()))

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByRole('region', { name: '선대 요약' })).toBeNull()
    expect(screen.queryByRole('region', { name: '선박 목록' })).toBeNull()
  })
})


/**
 * 규제 기준값 절과의 연결 (`#1516` · `#1239` 결정 A·B).
 *
 * ⑴ 「적용 기준」 한 줄은 규정 연도 표에서 **대시보드가 계산에 쓴 연도의 활성 행**을 찾아
 * 만든다 — 없으면 줄 자체가 없다(값을 지어내지 않는다). ⑵ 「기준값 없음」 선박에는
 * 기존 안내 문구를 그대로 둔 채 절로 가는 링크가 붙는다.
 */
describe('규제 기준값 절과의 연결 (#1516)', () => {
  function stubWithYears(
    years: Array<Record<string, unknown>>,
    vessels: Array<Record<string, unknown>> = [vessel('v1', '가선')],
  ) {
    const body = page(vessels as ReturnType<typeof vessel>[], { next_cursor: null, has_more: false })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = new URL(String(input), 'https://x')
        if (url.pathname.endsWith('/parameters/regulation-years')) {
          return { ok: true, status: 200, json: async () => ({ data: years }) } as Response
        }
        return { ok: true, status: 200, json: async () => body } as Response
      }),
    )
  }

  const YEAR_2026 = {
    year: 2026,
    z_factor_percent: '11.0',
    effective_from: '2026-01-01',
    source_ref: 'MEPC.400(83)',
    version: '2025-q2',
    is_active: true,
  }

  it('계산 연도의 활성 행이 있으면 출처·감축률을 문자열 그대로 실은 한 줄이 있다', async () => {
    stubWithYears([YEAR_2026])
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    const line = await screen.findByTestId('fleet-baseline')
    const text = line.textContent ?? ''
    expect(text).toContain('MEPC.400(83)')
    expect(text).toContain('11.0%')
    expect(within(line).getByRole('link').getAttribute('href')).toBe(regulationParametersPath())
  })

  it('계산 연도의 행이 없으면 한 줄을 그리지 않는다 — 다른 연도의 값을 붙이지 않는다', async () => {
    stubWithYears([{ ...YEAR_2026, year: 2025 }])
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    await screen.findByText('가선')
    expect(screen.queryByTestId('fleet-baseline')).toBeNull()
  })

  it('규정 연도 조회가 실패해도 선대 현황은 그대로 뜬다', async () => {
    const body = page([vessel('v1', '가선')], { next_cursor: null, has_more: false })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = new URL(String(input), 'https://x')
        if (url.pathname.endsWith('/parameters/regulation-years')) {
          return { ok: false, status: 500, json: async () => ({}) } as Response
        }
        return { ok: true, status: 200, json: async () => body } as Response
      }),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    expect(await screen.findByText('가선')).toBeTruthy()
    expect(screen.queryByTestId('fleet-baseline')).toBeNull()
  })

  it('「기준값 없음」 선박에는 안내 문구와 함께 절로 가는 링크가 붙는다', async () => {
    const missing = {
      ...vessel('v2', '나선'),
      data_available: false,
      ytd_attained_cii: null,
      ytd_required_cii: null,
      ytd_rating: null,
      unavailable_reason: 'NO_PARAMETERS',
    }
    stubWithYears([], [vessel('v1', '가선'), missing])
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    await screen.findByText('나선')
    const links = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href') === regulationParametersPath())
    // 기준값 없음 선박 한 척 → 링크 하나. 실적이 있는 선박에는 붙지 않는다.
    expect(links).toHaveLength(1)
    const row = links[0].closest('li') as HTMLElement
    expect(within(row).getByText('나선')).toBeTruthy()
  })

  it('실적이 있는 선박에는 그 링크가 없다', async () => {
    stubWithYears([])
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )

    await screen.findByText('가선')
    expect(
      screen.getAllByRole('link').some((link) => link.getAttribute('href') === regulationParametersPath()),
    ).toBe(false)
  })
})

/**
 * 배너는 한 주제 · 「가장 임박」은 요약 행 · 이미 D 이하 카드는 등급을 되풀이하지 않는다 (#1569).
 *
 * 종전 배너 부제 「가장 임박 — … · D등급까지 N일」은 위험 선박(이미 D · E)이 아닌 배를 가리켰고,
 * 위험 0척이라 배너가 없는 날에는 함께 사라졌다.
 */
describe('경고 배너 · D등급 진입 임박 (#1569)', () => {
  function renderWith(summary: Record<string, unknown>, rows: ReturnType<typeof vessel>[]) {
    const body = page(rows, { next_cursor: null, has_more: false })
    const withSummary = { ...body, data: { ...body.data, summary: { ...body.data.summary, ...summary } } }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => withSummary }) as Response),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
  }

  const SOONEST = { soonest_d_entry: { vessel_id: 'v9', name: '임박선', days: 36 } }
  const RISKY = {
    ...vessel('v1', '위험선'),
    ytd_rating: 'E',
    risk_reasons: ['E_THIS_YEAR'],
    days_to_d: null,
    days_to_d_reason: 'ALREADY_AT_OR_BELOW',
  }

  it('배너는 원문 한 줄만 — 가장 임박한 배를 말하지 않는다', async () => {
    renderWith({ at_risk: 1, ...SOONEST }, [RISKY])
    const banner = await screen.findByRole('alert')
    expect(banner.textContent).toBe('시정조치계획 대상 위험 선박 1척')
    expect(within(banner).queryByText(/임박/)).toBeNull()
  })

  it('요약 행에 「D등급 진입 임박」 — 일수와 선박 상세 링크', async () => {
    renderWith({ at_risk: 1, ...SOONEST }, [RISKY])
    const kpi = await screen.findByRole('region', { name: '선대 요약' })
    const cell = within(kpi).getByText('D등급 진입 임박').closest('.kpi') as HTMLElement
    expect(within(cell).getByText('36일')).toBeTruthy()
    expect(within(cell).getByRole('link', { name: '임박선' }).getAttribute('href')).toBe('/vessels/v9')
  })

  it('⚠️ 위험 0척이라 배너가 없어도 임박한 배는 보인다', async () => {
    renderWith({ at_risk: 0, ...SOONEST }, [vessel('v2', '보통선')])
    const kpi = await screen.findByRole('region', { name: '선대 요약' })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(within(kpi).getByRole('link', { name: '임박선' })).toBeTruthy()
  })

  it('후보가 없으면 「해당 선박 없음」', async () => {
    renderWith({ at_risk: 0, soonest_d_entry: null }, [vessel('v2', '보통선')])
    const kpi = await screen.findByRole('region', { name: '선대 요약' })
    const cell = within(kpi).getByText('D등급 진입 임박').closest('.kpi') as HTMLElement
    expect(within(cell).getByText('해당 선박 없음')).toBeTruthy()
  })

  it('이미 D 이하인 카드에는 「D등급 이하」가 없고 규제 플래그는 남는다', async () => {
    renderWith({ at_risk: 1, ...SOONEST }, [RISKY])
    const card = (await screen.findByText('위험선')).closest('li') as HTMLElement
    expect(within(card).queryByText('D등급 이하')).toBeNull()
    expect(within(card).getByText('E 1년차')).toBeTruthy()
  })
})

/**
 * 대시보드가 「실적 확정 전 항차」 카드를 그리는가 (#1573).
 *
 * 카드 자체는 `UnconfirmedVoyages.test.tsx`가 본다. 여기서는 **대시보드에 붙어 있고, 선대 요약
 * 다음에 오며, 그 조회가 실패해도 대시보드는 그대로인가**를 본다.
 */
describe('실적 확정 전 항차 카드의 자리 (#1573)', () => {
  const DQ = {
    data: {
      regulation_year: 2026,
      summary: {
        substituted_count: 0,
        unavailable_count: 0,
        anomaly_count: 0,
        unconfirmed_count: 1,
        anomaly_unjudged_count: 0,
        completeness_ratio: null,
      },
      vessels: [],
      issues: [
        {
          severity: 'UNCONFIRMED',
          vessel_id: 'v1',
          vessel_name: '가선',
          voyage_id: 'voy-1',
          voyage_no: '2026-01',
          codes: [],
          cii_impact: null,
          cii_impact_reason: null,
        },
      ],
    },
  }

  function stubWith(dq: 'ok' | 'fail' | 'empty') {
    const fleet = page([vessel('v1', '가선')], { next_cursor: null, has_more: false })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/fleet/data-quality')) {
          if (dq === 'ok') return { ok: true, status: 200, json: async () => DQ } as Response
          // #1824 — 0건일 때 칸이 서지 않는지 보려면 빈 응답이 필요하다.
          if (dq === 'empty')
            return { ok: true, status: 200, json: async () => ({ data: { issues: [] } }) } as Response
          return { ok: false, status: 500, json: async () => ({}) } as Response
        }
        return { ok: true, status: 200, json: async () => fleet } as Response
      }),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
  }

  /*
   * #1824 — **띠의 한 칸이 됐다.** 지도를 본문 전체로 펴면서 카드가 설 자리가
   * 없어졌고, `#1573`이 이미 「5건까지 보이고 나머지는 `2-11`로」를 정해 두었으므로
   * **넘기는 자리를 하나로 합쳤다**. 행별 「이 항차로」는 그 화면(`#1766`의 할 일 한
   * 목록)이 받는다.
   */
  it('선대 요약 띠 안에 건수 한 칸으로 있다', async () => {
    stubWith('ok')
    // 확정 전 항차는 대시보드와 **따로** 조회하므로 그 칸이 설 때까지 기다린다.
    const label = await screen.findByText('실적 확정 전 항차')
    const kpi = screen.getByRole('region', { name: '선대 요약' })
    expect(kpi.contains(label), '확정 전 항차 칸이 띠 안에 없다').toBe(true)
    const cell = label.closest('.kpi')!
    expect(within(cell as HTMLElement).getByText('1')).toBeTruthy()
    expect(
      within(cell as HTMLElement).getByRole('link', { name: '데이터 점검에서 처리' }),
    ).toBeTruthy()
  })

  it('0건이면 칸이 아예 서지 않는다 — 경고 배너와 같은 규칙', async () => {
    stubWith('empty')
    await screen.findByRole('region', { name: '선대 요약' })
    expect(screen.queryByText('실적 확정 전 항차')).toBeNull()
  })

  it('그 조회가 실패해도 대시보드는 그대로 그려진다', async () => {
    stubWith('fail')
    expect(await screen.findByText(/실적 확정 전 항차를 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.getByRole('region', { name: '선대 요약' })).toBeTruthy()
    expect(screen.getByText('가선')).toBeTruthy()
  })
})

describe('하단 고지는 배너 한 칸 (#1578)', () => {
  it('「추정값 사용」 문장이 면책 배너 안에 한 번만 있다 — 따로 떠 있는 문단이 없다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          ({
            ok: true,
            status: 200,
            json: async () => page([vessel('v1', '가')], { next_cursor: null, has_more: false }),
          }) as Response,
      ),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가')

    const hits = screen.getAllByText(/일부 값은 사용자 입력 또는 모델 추정값입니다/)
    expect(hits).toHaveLength(1)
    expect(hits[0].getAttribute('role')).toBe('note')
    expect(hits[0].textContent).toMatch(/^참고용 예측값입니다/)
  })
})
