// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AppShell } from './AppShell'
import { useShellContext } from './shellContext'
import { VESSEL_QUERY_KEY } from './globalContext'
import { SCREEN_BY_ID } from '../screens'

/**
 * 셸 → 화면 **전역 컨텍스트 배선** 검증 (#557).
 *
 * ## 이 파일이 보는 층
 *
 * `globalContext.ts`의 판정 규칙(우선순위·저장·주소 반영)은 순수 함수 테스트가 이미
 * 잠근다. 여기서 보는 것은 **셸이 그 값을 실제로 `Outlet`에 내려주는가**다.
 *
 * `#535`가 보고한 상태가 정확히 그 배선의 부재였다 — 상단바에서 배를 바꿔도 화면은
 * 그대로였고, 원인은 `<Outlet />`이 아무것도 넘기지 않는 것이었다. 규칙은 맞는데
 * **부르는 쪽이 없었으므로** 순수 함수 테스트로는 드러나지 않았다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const VESSELS = {
  data: [
    { id: '00000000-0000-4000-8000-000000000001', name: '샘플 벌크선', ship_type: 'BULK_CARRIER' },
    { id: '00000000-0000-4000-8000-000000000002', name: 'DONGJIN', ship_type: 'CONTAINER_SHIP' },
  ],
}

function stubServer() {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/auth/me')) {
        return jsonResponse({ data: { id: 'u1', email: 'a@b.c', display_name: '테스터' } })
      }
      if (url.includes('/vessels') && url.includes('/voyages')) return jsonResponse({ data: [] })
      if (url.includes('/vessels')) return jsonResponse(VESSELS)
      return jsonResponse({ data: [] })
    }),
  )
  return calls
}

/** 셸이 내려준 컨텍스트를 그대로 화면에 찍는 자식. 배선만 본다. */
function ContextProbe() {
  const context = useShellContext()
  return (
    <div>
      <span data-testid="vessel-id">{context.vesselId ?? '(없음)'}</span>
      <span data-testid="vessels-state">{context.vesselsState}</span>
      <span data-testid="vessel-count">{context.vessels.length}</span>
    </div>
  )
}

/*
 * 선박을 **쿼리로** 표현하는 화면에서 렌더한다.
 *
 * `globalContext.QUERY_CONTEXT_PATHS`가 그 화면을 셋으로 한정하고(`/voyage-cii` ·
 * `/annual-grade` · `/route-comparison`), 그 밖의 경로에서는 쿼리를 읽지 않는다.
 * 키 이름도 `vessel_id`로 고정돼 있다 — 처음에 `/?vessel=…`로 적었다가 이 테스트가
 * 「선택 없음」을 내서 알았다.
 */
const FORECAST_PATH = SCREEN_BY_ID.CII_FORECAST.path

function renderShell(path = `${FORECAST_PATH}?${VESSEL_QUERY_KEY}=00000000-0000-4000-8000-000000000002`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path={FORECAST_PATH} element={<ContextProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('셸이 Outlet으로 컨텍스트를 내려준다 (#484 · #535)', () => {
  it('주소의 선박이 화면까지 도달한다', async () => {
    stubServer()

    renderShell()

    await waitFor(() =>
      expect(screen.getByTestId('vessel-id').textContent).toBe(
        '00000000-0000-4000-8000-000000000002',
      ),
    )
  })

  it('선박 목록도 함께 내려간다 — 화면이 GET /vessels를 다시 부르지 않는다', async () => {
    stubServer()

    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessel-count').textContent).toBe('2'))
    expect(screen.getByTestId('vessels-state').textContent).toBe('ready')
  })

  it('조회 실패는 빈 목록이 아니라 failed로 구분된다', async () => {
    // `ready`인데 비었으면 「등록된 배가 없다」, `failed`면 「서버를 못 읽었다」이다.
    // 두 상태에 같은 문구를 쓰면 사용자는 무엇을 해야 하는지 알 수 없다.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({ data: { id: 'u1', email: 'a@b.c', display_name: '테스터' } })
        }
        return jsonResponse(null, 500)
      }),
    )

    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('failed'))
    expect(screen.getByTestId('vessel-count').textContent).toBe('0')
  })
})

describe('사이드바 — 미구현 화면을 숨기지 않고 비활성으로 노출한다 (#542 이름 정정 후)', () => {
  it('구현된 화면은 링크로, 그렇지 않은 화면은 링크가 아니다', async () => {
    stubServer()

    renderShell()

    // 대시보드는 `implemented: true`라 링크다.
    await waitFor(() => expect(screen.getByRole('link', { name: /대시보드/ })).toBeDefined())
    // 설정은 `implemented: false`(#359 결정 대기)라 링크가 아니다.
    expect(screen.queryByRole('link', { name: /^설정/ })).toBeNull()
  })
})

describe('셸 조회가 한 번만 나간다 — 무한 루프 회귀 (#557)', () => {
  it('선박 목록 조회가 반복되지 않는다', async () => {
    const calls = stubServer()

    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessel-count').textContent).toBe('2'))
    await new Promise((resolve) => setTimeout(resolve, 150))

    const vesselCalls = calls.filter((u) => u.includes('/vessels') && !u.includes('/voyages'))
    expect(vesselCalls).toHaveLength(1)
  })
})
