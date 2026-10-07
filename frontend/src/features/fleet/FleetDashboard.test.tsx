// @vitest-environment jsdom
import '../../test/renderSetup'

/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
/*
 * 대역이지만 **마커는 그린다** (#1831).
 *
 * 마커 팝오버를 보려면 누를 대상이 있어야 하고, 무엇보다 **마커 DOM이 목록이 바뀔 때
 * 새로 만들어진다**는 성질을 그대로 흉내 내야 한다 — 그것이 이 기능의 함정이기 때문이다
 * (개발 쪽 코드 점검 09-24). 진짜 `FleetMap`과 같은 규칙만 지킨다: 좌표가 있는 배마다
 * `data-vessel-id`를 가진 버튼 하나, `fleetmap__marker` 클래스, 누르면 `onSelectVessel`.
 */
vi.mock('./FleetMap', async () => {
  const { useMemo } = await import('react')
  /*
   * **선박 목록이 갈리면 마커 노드를 버리고 새로 만든다.**
   *
   * 진짜 `FleetMap`은 마커를 명령형으로 만들어 지도에 붙이므로 `vessels`가 새 배열이 되면
   * DOM 노드가 전부 새것이 된다. React 대역은 `key`가 같으면 노드를 **재사용**해 그 성질이
   * 사라진다 — 그러면 이 파일의 검사가 「id로 쥔다」를 잠그지 못하고 초록이 된다.
   * 세대 번호를 `key`에 실어 같은 일이 벌어지게 한다.
   */
  let generations = 0
  return {
    FleetMap: ({
      vessels,
      onSelectVessel,
      focusVesselId,
      focusNonce,
    }: {
      vessels: readonly { id: string; name: string; lat: string | null; lon: string | null }[]
      onSelectVessel?: (id: string) => void
      focusVesselId?: string | null
      focusNonce?: number
    }) => {
      const generation = useMemo(() => `${(generations += 1)}:${vessels.length}`, [vessels])
      return (
        <div className="fleetmap__canvas" data-focus={`${focusVesselId ?? ''}:${focusNonce ?? 0}`}>
          {vessels
            .filter((v) => v.lat !== null && v.lon !== null)
            .map((v) => (
              <button
                key={`${v.id}-${generation}`}
                type="button"
                className="fleetmap__marker"
                data-vessel-id={v.id}
                aria-label={`${v.name} · 등급 B`}
                onClick={() => onSelectVessel?.(v.id)}
              />
            ))}
        </div>
      )
    },
  }
})

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
    imo_number: '9100011',
    underway_state: 'UNDER_WAY',
    detail_status: 'SAILING',
    /* 좌표는 실제로 nullable이다 — 좌표가 **있는** 배를 만드는 검사(#1831)가 덮어쓴다. */
    current_lat: null as string | null,
    current_lon: null as string | null,
    position_updated_at: null,
    is_cii_applicable_hint: true,
    /* GT 미입력(`null`) 선박을 만드는 검사(#2132)가 덮어쓴다. */
    gross_tonnage: 30000 as number | null,
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
  // 10/7(#2311) — 「조치 필요」 카드가 「확인할 선박」 표 카드로 합쳐졌다. 진입은 그 카드 아래 한 줄이다.
  it('조치 항목이 있으면 확인할 선박 카드에 「데이터 점검」 링크가 있다', async () => {
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
    await screen.findAllByText('가선')
    const card = screen.getByRole('region', { name: '확인할 선박' })
    const link = within(card).getByRole('link', { name: '데이터 점검' })
    expect(link.getAttribute('href')).toBe('/data-quality')
  })
})


/*
 * 「조치 필요」 결과 카드(#2200)는 10/7 시안 01(#2311)로 「확인할 선박」 표에 합쳐졌다. 결론
 * 한 줄(「조치가 필요한 선박 N척 — …」)과 카드 맨 아래 「함대 감축 계획 세우기」는 걷혔고, 같은
 * 일을 행마다 「왜 · 다음 작업」이 한다. 여기서는 그 표가 조치를 어떻게 싣는지 본다.
 */
describe('확인할 선박 — 조치가 걸린 배 (#2200 → #2311)', () => {
  it('조치가 걸린 배가 맨 위이고, 「왜」는 조치 문구 · 「다음 작업」은 감축 계획이다 — 머리줄에는 링크가 없다', async () => {
    const body = page([vessel('v1', '가선'), vessel('v2', '나선')], { next_cursor: null, has_more: false })
    body.data.actions = [
      { vessel_id: 'v2', vessel_name: '나선', reason: 'D_THIRD_YEAR', severity: 'warning', message: 'D등급 3년 연속' },
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
    await screen.findAllByText('가선')
    const card = screen.getByRole('region', { name: '확인할 선박' })
    const head = card.querySelector('.card__head') as HTMLElement
    expect(within(head).queryAllByRole('link')).toHaveLength(0)

    const table = within(card).getByRole('table')
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      '선박',
      '누적 등급',
      '다음 작업',
    ])
    const rows = within(table).getAllByRole('row').slice(1)
    // 받은 순서는 가선 → 나선이지만 조치가 걸린 나선이 위로 온다
    expect(within(rows[0]).getByRole('link', { name: '나선' })).toBeTruthy()
    expect(within(rows[0]).getByText('D등급 3년 연속')).toBeTruthy()
    const next = within(rows[0]).getByRole('link', { name: /감축 계획/ })
    expect(next.getAttribute('href')).toBe('/fleet-reduction')
    // 조치가 없는 배에는 감축 계획 링크가 없다
    expect(within(rows[1]).queryByRole('link', { name: /감축 계획/ })).toBeNull()
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
/*
 * 목록 자리 — 10/7 시안 01(#2311)로 지도 위 패널의 「선박 목록」이 지도 옆 「확인할 선박」
 * 표 카드가 됐다. 정렬 · 오류 · 「다음 선박」이 모두 이 카드 안에 있다.
 */
const LIST_NAME = '확인할 선박'

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
    const list = screen.getByRole('region', { name: LIST_NAME })
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
    expect(within(screen.getByRole('region', { name: LIST_NAME })).queryByRole('alert')).toBeNull()
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

    const alert = await within(screen.getByRole('region', { name: LIST_NAME })).findByRole('alert')
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
    const list = screen.getByRole('region', { name: LIST_NAME })
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
    await within(screen.getByRole('region', { name: LIST_NAME })).findByRole('alert')

    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'grade' } })
    await waitFor(() => expect(pending).toHaveLength(3))
    await act(async () =>
      pending[2].d.resolve(ok(page([vessel('v9', '라선')], { next_cursor: null, has_more: false }))),
    )

    expect(await screen.findByText('라선')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: LIST_NAME })).queryByRole('alert')).toBeNull()
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
    expect(screen.queryByRole('region', { name: LIST_NAME })).toBeNull()
  })
})

/**
 * 첫 조회 실패 뒤 다시 시도 (`#1871` ①).
 *
 * 받아 둔 목록이 없을 때의 전면 오류(위 「그대로 화면 전체의 오류다」)는 종전에
 * 메시지만 그리고 버튼이 없었다 — 서버가 살아나도 벗어날 길이 새로고침뿐인데,
 * 새로고침은 `RequireAuth`가 네트워크 실패를 비인증으로 읽어 로그인 화면으로
 * 보내(`#278`·`#542`) 회복 경로가 아니다. 여기서는 목록 실패 재시도(`#1814`)와
 * **같은 경로**(`retryKey`)로 첫 페이지를 다시 불러 화면이 목록으로 넘어가는가를
 * 본다. 오류 메시지는 표시 문구라 리터럴로 단언하지 않는다(`AGENTS §4.6`) — 「다시
 * 시도」는 `ErrorState`가 갖는 정본 문구(`PRD §6.4`)라 리터럴로 둔다.
 */
describe('첫 조회 실패 뒤 다시 시도 (#1871)', () => {
  const failed = () =>
    ({ ok: false, status: 502, json: async () => ({ error: { message: '잠시 뒤' } }) }) as Response

  it('전면 오류에 「다시 시도」가 있고, 누르면 첫 페이지를 다시 불러 목록이 그려진다', async () => {
    const { pending, ok } = deferredFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending[0].d.resolve(failed()))

    const alert = await screen.findByRole('alert')
    // 문구가 아니라 「오류로 무언가는 뜬다」·「목록은 아직 없다」는 성질만 본다
    expect((alert.textContent ?? '').length).toBeGreaterThan(0)
    expect(screen.queryByRole('region', { name: LIST_NAME })).toBeNull()

    // 정본 문구 (PRD §6.4) — 바꾸려면 PRD 개정이 먼저다.
    const retry = within(alert).getByRole('button', { name: '다시 시도' })
    fireEvent.click(retry)

    // 실패한 것과 같은 첫 페이지 조회를 다시 부른다
    await waitFor(() => expect(pending).toHaveLength(2))
    // 응답을 기다리는 동안은 오류도 「다시 시도」도 없다 — 두 번 눌러 요청이 겹치지 않는다
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    await act(async () => pending[1].d.resolve(ok(first())))

    expect(await screen.findByText('가선')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('region', { name: LIST_NAME })).toBeTruthy()
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
    // 10/7(#2311) — 선박 카드 목록이 「확인할 선박」 표가 됐다. 링크는 그 배의 행 안이다.
    const row = links[0].closest('tr') as HTMLElement
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

  /*
   * 10/7(#2311) — 선박 카드의 규제 플래그 배지는 「확인할 선박」 표의 「왜」 칸(서버 조치 문구)이
   * 대신한다. 「D등급 이하」를 되풀이하지 않는다는 것(#1569)은 그대로다.
   */
  it('이미 D 이하인 행에는 「D등급 이하」가 없고, 「왜」 칸이 조치 사유를 말한다', async () => {
    const body = page([RISKY], { next_cursor: null, has_more: false })
    body.data.actions = [
      { vessel_id: 'v1', vessel_name: '위험선', reason: 'E_THIS_YEAR', severity: 'critical', message: 'E등급 1년차' },
    ] as never
    const withSummary = { ...body, data: { ...body.data, summary: { ...body.data.summary, at_risk: 1, ...SOONEST } } }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => withSummary }) as Response),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    const row = (await screen.findByRole('link', { name: '위험선' })).closest('tr') as HTMLElement
    expect(within(row).queryByText('D등급 이하')).toBeNull()
    expect(within(row).getByText('E등급 1년차')).toBeTruthy()
  })

  it('⚠️ CII 적용 대상이 아닌 E등급 선박은 「규제 대상 아님」 배지가 붙고 위험 선박이 아니다 (#2132)', async () => {
    // 서버가 `risk_reasons`를 비우고 `at_risk`에서 뺀다 — 화면은 그 값을 그대로 쓴다.
    // GT를 알고 5,000 미만이면 E여도 시정조치계획 대상이 아니다(`PRD §3.3.7`).
    // 그 이유가 같은 행에 없으면 「E · 이상 없음」이 모순으로 읽힌다 — 선박명 칸에 배지를 둔다
    // (`DESIGN_SYSTEM §8.2` 「선박을 식별하는 자리마다」).
    const small = {
      ...vessel('v1', '소형선'),
      ytd_rating: 'E',
      is_cii_applicable_hint: false,
      gross_tonnage: 4559,
      risk_reasons: [] as string[],
      days_to_d: null,
      days_to_d_reason: 'ALREADY_AT_OR_BELOW',
    }
    renderWith({ at_risk: 0 }, [small])
    const row = (await screen.findByRole('link', { name: '소형선' })).closest('tr') as HTMLElement
    const badge = within(row).getByRole('img', { name: /소형선/ })
    // 정본 문구 (DESIGN_SYSTEM §8.2) — 바꾸려면 정본 개정이 먼저다.
    expect(badge.textContent).toBe('규제 대상 아님')
    // 배지는 선박을 식별하는 칸(선박명 칸)에 붙는다.
    expect(badge.closest('td')).toBe(within(row).getByRole('link', { name: '소형선' }).closest('td'))
    // 위험 선박이 아니다 — 조치 행으로 올라가지 않고 경고 배너도 서지 않는다.
    expect(row.className).not.toContain('check__row--action')
    expect(within(row).queryByText(/E등급 1년차/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('GT 미입력 선박(E)의 행에는 「GT 미입력」 배지가 붙는다 — 「규제 대상 아님」으로 합치지 않는다 (#2132)', async () => {
    // GT가 비어 있으면 판정 불가다. 서버는 이 배를 위험 판정에 남긴다(`PRD §3.3.7` 결정 1).
    const noGt = {
      ...vessel('v2', '톤수없는선'),
      ytd_rating: 'E',
      is_cii_applicable_hint: false,
      gross_tonnage: null,
      risk_reasons: ['E_THIS_YEAR'],
      days_to_d: null,
      days_to_d_reason: 'ALREADY_AT_OR_BELOW',
    }
    renderWith({ at_risk: 1 }, [noGt])
    const row = (await screen.findByRole('link', { name: '톤수없는선' })).closest('tr') as HTMLElement
    const badge = within(row).getByRole('img', { name: /톤수없는선/ })
    // 정본 문구 (DESIGN_SYSTEM §8.2) — 바꾸려면 정본 개정이 먼저다.
    expect(badge.textContent).toBe('GT 미입력')
    // 정본 문구 (DESIGN_SYSTEM §8.2) — 바꾸려면 정본 개정이 먼저다.
    expect(within(row).queryByText('규제 대상 아님')).toBeNull()
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

/**
 * 마커 팝오버가 화면에 붙는 자리 (#1831).
 *
 * 카드 자체는 `VesselPopover.test.tsx`가, 마커가 버튼인지는 `FleetMap.test.tsx`가 본다.
 * 여기서 보는 것은 **조립**이다 — 한 번에 하나 · 마커가 새로 만들어졌을 때 · 초점 복귀 ·
 * 패널 행에서 여는 길.
 */
describe('선대 대시보드 — 마커 팝오버 (#1831)', () => {
  /** 좌표가 있는 배와 **지도 자산이 있는 환경**(`206`)을 함께 흉내 낸다. */
  function stubFetchWithMap() {
    const placed = (id: string, name: string) => ({
      ...vessel(id, name),
      current_lat: '35.1000',
      current_lon: '129.0000',
    })
    const fetchImpl = vi.fn(async (input: unknown) => {
      const raw = String(input)
      /*
       * 지도 자산 유무를 묻는 Range 요청 (`#763` · `basemap.hasBasemap`).
       * `206` **이면서** 앞머리가 PMTiles 매직(`PMTiles`)이어야 「있다」다 — 둘 중
       * 하나만 흉내 내면 개략도로 떨어져 마커가 아예 없다.
       */
      if (raw.includes('.pmtiles')) {
        const magic = new Uint8Array([0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73])
        return {
          ok: true,
          status: 206,
          body: null,
          arrayBuffer: async () => magic.buffer,
        } as unknown as Response
      }
      const url = new URL(raw, 'https://x')
      const body = url.searchParams.get('cursor')
        ? page([placed('v3', '다선')], { next_cursor: null, has_more: false })
        : page([placed('v1', '가선'), placed('v2', '나선')], { next_cursor: 'c2', has_more: true })
      return { ok: true, status: 200, json: async () => body } as Response
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  const marker = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name} ·`) })
  /** 지도는 `lazy()` + 자산 조회 뒤에 붙는다 — 목록이 떠도 마커는 한 박자 늦다. */
  const findMarker = (name: string) =>
    screen.findByRole('button', { name: new RegExp(`^${name} ·`) })

  it('마커를 누르면 그 배의 카드가 열리고, 다른 마커를 누르면 하나만 남는다', async () => {
    stubFetchWithMap()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')

    fireEvent.click(await findMarker('가선'))
    await waitFor(() => expect(screen.getByRole('dialog', { name: '가선 요약' })).toBeTruthy())

    fireEvent.click(marker('나선'))
    await waitFor(() => expect(screen.getByRole('dialog', { name: '나선 요약' })).toBeTruthy())
    // **한 번에 하나** — 앞의 카드가 남아 있으면 지도에 카드가 쌓인다.
    expect(screen.queryByRole('dialog', { name: '가선 요약' })).toBeNull()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  /**
   * **마커가 새로 만들어져도 카드가 그 배에 다시 붙는다** (개발 쪽 지적 · 09-24).
   *
   * 「다음 선박 불러오기」는 `vessels`를 새 배열로 만들고, 그러면 마커 DOM이 전부 새
   * 노드가 된다. 카드를 **요소로** 쥐고 있었다면 이 순간 기준점을 잃고 초점이 `body`로
   * 떨어진다 — 그래서 선박 id로 쥔다.
   */
  it('목록이 늘어 마커가 새로 만들어져도 카드는 그 배에 붙어 있다', async () => {
    stubFetchWithMap()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')
    fireEvent.click(await findMarker('가선'))
    await waitFor(() => expect(screen.getByRole('dialog', { name: '가선 요약' })).toBeTruthy())
    const before = marker('가선')

    fireEvent.click(screen.getByRole('button', { name: /다음 선박 불러오기/ }))
    await screen.findByText('다선')

    // 마커는 새 노드다 — 그런데도 카드는 살아 있고 같은 배를 가리킨다.
    expect(marker('가선')).not.toBe(before)
    expect(screen.getByRole('dialog', { name: '가선 요약' })).toBeTruthy()
  })

  it('그 배가 목록에서 사라지면 카드를 닫는다 — 기준점 없는 카드를 남기지 않는다', async () => {
    /*
     * 종전 검사는 정렬을 바꾼 뒤에도 **같은 두 척**이 돌아오는 대역을 써서 「나선」이
     * 사라지는 일이 없었고, 단언도 「카드가 남아 있다」였다 — 제목과 반대다 (`#2145`).
     * 여기서는 이름순 첫 페이지에서 「나선」을 빼고, 위험순으로 돌아오면 다시 넣는다.
     */
    const fetchImpl = stubFetchWithMap()
    const base = fetchImpl.getMockImplementation()!
    fetchImpl.mockImplementation(async (input: unknown) => {
      const raw = String(input)
      const url = new URL(raw, 'https://x')
      if (!raw.includes('.pmtiles') && url.searchParams.get('sort') === 'name') {
        const only = { ...vessel('v1', '가선'), current_lat: '35.1000', current_lon: '129.0000' }
        const body = page([only], { next_cursor: null, has_more: false })
        return { ok: true, status: 200, json: async () => body } as Response
      }
      return base(input)
    })
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('나선')
    fireEvent.click(await findMarker('나선'))
    await waitFor(() => expect(screen.getByRole('dialog', { name: '나선 요약' })).toBeTruthy())

    // 이름순 첫 페이지에는 「나선」이 없다 — 마커도 카드도 사라진다.
    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'name' } })
    await waitFor(() => expect(screen.queryByRole('button', { name: /^나선 ·/ })).toBeNull())
    expect(marker('가선')).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    // **닫은 것이지 가린 것이 아니다** — 그 배가 목록에 돌아와도 카드가 저절로 다시 뜨지 않는다.
    fireEvent.change(screen.getByTestId('fleet-sort'), { target: { value: 'risk' } })
    await findMarker('나선')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('닫으면 초점이 눌렀던 마커로 돌아간다 — body로 떨어지지 않는다', async () => {
    stubFetchWithMap()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')
    fireEvent.click(await findMarker('가선'))
    await waitFor(() => expect(screen.getByRole('dialog', { name: '가선 요약' })).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(marker('가선'))
  })

  it('패널 행의 「지도에서 보기」가 그 배를 지도에 넘긴다 — 지도를 옮긴 뒤 열리는 길이다', async () => {
    stubFetchWithMap()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')

    fireEvent.click(screen.getByRole('button', { name: '지도에서 나선 보기' }))
    await waitFor(() =>
      expect(document.querySelector('.fleetmap__canvas')?.getAttribute('data-focus')).toBe('v2:1'),
    )
  })
})

/**
 * ⚠️ 지도가 읽는 표시를 패널이 실제로 단다 (#2051).
 *
 * ## 왜 따로 잠그나
 *
 * 지도 어댑터는 `[data-map-overlay]`를 **읽기만** 한다. 대시보드가 그 표시를
 * 떼어도 지도 쪽 검사는 전부 초록이다 — 덮는 것이 없다고 읽고 종전 패딩을 내기
 * 때문이다. 화면에서는 선박이 다시 패널 밑으로 몰리는데 **아무도 붉어지지 않는다.**
 * `#2015`·`#2038`·`#2046`·`#2047`이 전부 「규칙이 화면에 닿지 않는다」의 사본이었다.
 *
 * 이름을 여기 문자열로 적지 않고 **지도 소스에서 읽어** 대조한다. 한쪽만 바꿔도
 * 갈리지 않게 하려는 것이고, 그 방향은 `reasonCodes.sync.test.ts`가 정본을 읽는 것과 같다.
 */
describe('지도 위 패널의 「덮고 있다」 표시 (#2051 → #2311)', () => {
  const overlayAttribute = (() => {
    /*
     * jsdom 환경에서는 `import.meta.url`이 `file:`이 아니라 개발 서버 주소라
     * `fileURLToPath`가 던진다 — `stickyTop.sync.test.ts`와 같이 작업 폴더에서 잡는다.
     */
    const source = readFileSync(join(process.cwd(), 'src/features/map/mapLibreRenderer.ts'), 'utf-8')
    const found = /const MAP_OVERLAY_ATTRIBUTE = '([^']+)'/.exec(source)
    if (!found) throw new Error('mapLibreRenderer.ts에서 MAP_OVERLAY_ATTRIBUTE를 찾지 못했습니다')
    return found[1]
  })()

  it('표시 이름이 지도 어댑터가 찾는 것과 같다', () => {
    // 이름이 갈리면 아래 검사가 무엇을 보는지 알 수 없어지므로 먼저 못 박는다.
    expect(overlayAttribute).toBe('data-map-overlay')
  })

  /*
   * 10/7 시안 01(#2311) — 지도 위 좌측 패널이 걷히고 목록은 지도 옆 표 카드가 됐다. 이제 지도를
   * 덮는 것이 없으므로 범위는 **선박 위치만으로** 잡혀야 한다 — 표시가 남아 있으면 지도가 없는
   * 패널만큼 비켜 범위를 잡는다.
   */
  it('지도를 덮는 패널이 없다 — 대시보드 어디에도 그 표시가 없다', async () => {
    stubFetch()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findAllByText('가선')
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(document.querySelector(`[${overlayAttribute}]`)).toBeNull()
  })
})

/**
 * 숫자가 **무엇을 센 값인지** (#2121).
 *
 * 세 자리 모두 값은 맞았고 뜻이 어긋나 있었다. 지도 칩은 불러온 선박 수를 「그려진 척수」
 * 자리에 적었고, 접힌 패널은 불러온 페이지 수를 선대 전체 수 옆에 적었고, 「n분 전」은
 * 화면을 연 순간에 멈춰 있었다.
 */
describe('숫자가 센 것과 표시가 같다 (#2121)', () => {
  function stubPositions() {
    const located = { ...vessel('v1', '가선'), current_lat: '35.1000', current_lon: '129.0400' }
    const adrift = vessel('v2', '나선') // 좌표 없음 — 마커가 없다
    const body = page([located, adrift], { next_cursor: 'c2', has_more: true })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response),
    )
  }

  it('지도 카드의 척수는 **그려진** 척수다 — 위치 없는 배를 세지 않는다', async () => {
    stubPositions()
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByText('가선')
    // 10/7(#2311) — 지도 칩은 「현재 위치」 카드 머리의 메타가 됐다.
    const chip = document.querySelector('.fleet__mapcard .card__meta') as HTMLElement
    // 불러온 배는 둘, 좌표가 있는 배는 하나다.
    expect(chip.textContent).toContain('1척')
    expect(chip.textContent).not.toContain('2척')
  })

  it('「n분 전」이 화면을 열어 둔 동안에도 흐른다', async () => {
    stubPositions()
    // 요약의 기준 시각(`as_of`)은 12:00이다 — 그 30초 뒤에 화면을 연다.
    vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date('2026-08-16T12:00:30Z') })
    try {
      render(
        <MemoryRouter>
          <FleetDashboard />
        </MemoryRouter>,
      )
      await screen.findByText('가선')
      const relative = () => (document.querySelector('.fleet__asof-rel') as HTMLElement).textContent
      const opened = relative()

      // 1분 간격 시계가 다섯 번 돌게 1분씩 민다 — 한 번에 5분을 밀면 CI에서 한 박자 늦게
      // 그려진 시계가 그 사이를 놓쳤다(#2330 CI). 그린 뒤의 글자를 기다려 본다.
      for (let minute = 0; minute < 5; minute += 1) {
        await act(async () => {
          vi.advanceTimersByTime(60_000)
        })
      }
      // 문구가 아니라 **바뀌었다**를 본다 — 5분이 지났는데 같은 글자면 멈춘 것이다.
      await waitFor(() => expect(relative()).not.toBe(opened))
    } finally {
      vi.useRealTimers()
    }
  })
})

/*
 * 요약 문장 한 줄(#2199)은 10/7 디자인 결정(#2311)으로 걷혔다 — 경고 배너 · 숫자 칸과 같은 정보를
 * 한 화면에 두 번 말했다. 종전 두 검사(문장 모양 · 없을 때 줄을 두지 않음)는 지키던 동작이 없어져
 * 지웠고, 되살아나지 않는지만 본다.
 */
describe('요약 문장을 두지 않는다 (#2199 → #2311)', () => {
  it('E등급 선박과 D 진입 임박 선박이 있어도 문장 줄이 없고, 첫 문장은 경고 배너뿐이다', async () => {
    const body = page([vessel('v1', '가선')], { next_cursor: null, has_more: false })
    const withSummary = {
      ...body,
      data: {
        ...body.data,
        summary: {
          ...body.data.summary,
          at_risk: 2,
          rating_distribution: { A: 0, B: 1, C: 0, D: 0, E: 2 },
          soonest_d_entry: { vessel_id: 'v9', name: '임박선', days: 39 },
        },
      },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => withSummary }) as Response),
    )
    render(
      <MemoryRouter>
        <FleetDashboard />
      </MemoryRouter>,
    )
    await screen.findByRole('region', { name: '선대 요약' })
    expect(screen.queryByTestId('fleet-summary')).toBeNull()
    const lead = document.querySelector('.fleet__lead') as HTMLElement
    expect(within(lead).getByRole('alert')).toBeTruthy()
    expect(lead.querySelectorAll('p, a').length).toBe(1)
  })
})

/**
 * 10/7 대시보드 개편 (#2311) — 표 5 : 지도 7, 등급 분포 막대, 기준 문구는 면책 바로 위,
 * GT 미입력 칸은 0이면 서지 않는다. 문구는 성질로 본다(`AGENTS §4.6`).
 */
describe('대시보드 개편 배치 (#2311)', () => {
  function renderWith(summary: Record<string, unknown> = {}) {
    const body = page([vessel('v1', '가선')], { next_cursor: null, has_more: false })
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

  it('한 격자 안에 확인할 선박 표가 먼저, 지도 카드가 다음이다', async () => {
    renderWith()
    await screen.findAllByText('가선')
    const grid = document.querySelector('.fleet__grid') as HTMLElement
    const cards = [...grid.children]
    expect(cards).toHaveLength(2)
    expect(cards[0]).toBe(screen.getByRole('region', { name: '확인할 선박' }))
    expect(within(cards[1] as HTMLElement).getByRole('heading', { level: 2 }).textContent).toBe('현재 위치')
  })

  it('등급 분포는 배지 표기 막대이고 0척이 아닌 등급마다 글자를 늘 그린다 — 무늬가 없다', async () => {
    renderWith({ rating_distribution: { A: 0, B: 2, C: 0, D: 0, E: 1 } })
    const strip = await screen.findByRole('region', { name: '선대 요약' })
    const bar = strip.querySelector('.dist__bar--badge') as HTMLElement
    expect(bar).toBeTruthy()
    expect(bar.querySelector('svg')).toBeNull()
    const segs = [...bar.querySelectorAll('.dist__seg')]
    expect(segs).toHaveLength(2)
    // 글자가 구간 안에 있으면 툴팁 · 초점 경로가 필요 없다
    for (const seg of segs) expect(seg.hasAttribute('title')).toBe(false)
  })

  it('기준 시각 줄은 면책 배너 바로 위다', async () => {
    renderWith()
    await screen.findAllByText('가선')
    const meta = document.querySelector('.fleet__meta') as HTMLElement
    expect(meta.querySelector('.fleet__asof')).toBeTruthy()
    expect(meta.nextElementSibling?.classList.contains('disclaimer-banner')).toBe(true)
  })

  it('GT 미입력 칸은 0척이면 서지 않고, 1척 이상이면 선다', async () => {
    renderWith({ missing_gross_tonnage: 0 })
    const strip = await screen.findByRole('region', { name: '선대 요약' })
    expect(within(strip).queryByText('GT 미입력')).toBeNull()
    cleanup()

    renderWith({ missing_gross_tonnage: 2 })
    const again = await screen.findByRole('region', { name: '선대 요약' })
    const cell = within(again).getByText('GT 미입력').closest('.kpi') as HTMLElement
    expect(within(cell).getByText('2')).toBeTruthy()
  })
})
