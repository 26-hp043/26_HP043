// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AppShell } from './AppShell'
import { useShellContext } from './shellContext'
import { VESSEL_QUERY_KEY } from './globalContext'
import { NAV_ORDER, SCREEN_BY_ID } from '../screens'
import * as session from '../auth/session'

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
        // 기존 검사는 전 화면이 열린 사무직을 전제한다. 현장직은 아래 별도 describe.
        return jsonResponse({
          data: { id: 'u1', email: 'a@b.c', display_name: '테스터', role: 'OFFICE' },
        })
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
  /*
   * 종전 이 테스트는 **설정**을 「링크가 아닌 화면」의 예로 썼다. `#506`으로 설정이
   * 실 API로 돌게 되어 **`NAV_ORDER` 7개가 전부 `implemented: true`**가 됐고,
   * 비활성 분기는 지금 도달할 수 있는 사이드바 화면이 없다.
   *
   * 분기 자체를 지우지 않는다 — 앞으로 미구현 화면이 사이드바에 다시 들어올 수 있고,
   * 그때 「숨기지 않고 비활성으로」라는 `#542` 결정이 지켜지는지는 `screens.test.ts`의
   * 불변식(`implemented` ↔ `ComingSoon` 대응)이 지킨다.
   */
  it('사이드바 화면이 전부 링크다 — 막힌 메뉴가 없다', async () => {
    stubServer()

    renderShell()

    await waitFor(() => expect(screen.getByRole('link', { name: /대시보드/ })).toBeDefined())
    for (const id of NAV_ORDER) {
      const label = SCREEN_BY_ID[id].label
      expect(
        screen.queryByRole('link', { name: new RegExp(`^${label}`) }),
        `사이드바에서 막혀 있다: ${label}`,
      ).not.toBeNull()
    }
  })
})

describe('셸 flex의 흐름 안 항목은 사이드바와 본문 둘뿐이다 (#1693)', () => {
  it('사이드바 앞에 gap을 차지하는 형제가 없다 — `§7.1` 외곽 여백 24', () => {
    stubServer()
    const { container } = renderShell()
    const shell = container.querySelector('.app-shell') as HTMLElement
    // jsdom은 CSS 파일을 적용하지 않으므로 흐름 밖은 두 가지로 판정한다:
    // 인라인 `position: absolute`(패턴 정의 SVG) · `.skip-link`(global.css에서 absolute).
    const inFlow = [...shell.children].filter((child) => {
      const el = child as HTMLElement
      if (el.style?.position === 'absolute') return false
      if (el.classList.contains('skip-link')) return false
      return true
    })
    expect(inFlow.map((el) => el.classList[0])).toEqual(['app-shell__sidebar', 'app-shell__stack'])
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

/*
 * 화면이 깨져도 셸은 남는다 (`#823`).
 *
 * ## 왜 컴포넌트 검사만으로는 부족한가
 *
 * `ErrorBoundary.test.tsx`가 경계 **자체**를 잠근다. 하지만 그 경계가 셸에 실제로
 * 배선됐는지는 보지 않는다 — `#535`가 정확히 그 층에서 났던 결함이다(규칙은 맞는데
 * 부르는 쪽이 없었다). 실제로 배선의 `key`를 지워도 컴포넌트 검사 11건은 전부
 * 통과했다.
 *
 * 그래서 여기서는 **진짜 `AppShell`에 던지는 화면을 물려** 셸이 남는지 본다.
 */

/** 렌더 중 던지는 화면. */
function BoomScreen(): never {
  throw new Error('화면이 터졌다')
}

const MANAGEMENT_PATH = SCREEN_BY_ID.VESSEL_MANAGEMENT.path

function renderShellWithBoom(path: string = FORECAST_PATH) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path={FORECAST_PATH} element={<BoomScreen />} />
          <Route path={MANAGEMENT_PATH} element={<div>다른 화면</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('화면이 깨져도 셸은 남는다 (#823)', () => {
  it('오류 화면을 그리고 사이드바는 살아 있다', async () => {
    stubServer()
    vi.spyOn(console, 'error').mockImplementation(() => {})

    renderShellWithBoom()

    expect(await screen.findByText('화면을 표시하지 못했습니다')).toBeTruthy()
    // 셸이 남아야 사용자가 다른 화면으로 갈 수 있다 — 이것이 루트 경계와의 차이다.
    expect(screen.getByRole('navigation')).toBeTruthy()
    expect(
      screen.getByRole('link', { name: new RegExp(SCREEN_BY_ID.VESSEL_MANAGEMENT.label) }),
    ).toBeTruthy()
  })

  it('오류 화면 안에도 나갈 길이 있다 — 「대시보드로」', async () => {
    stubServer()
    vi.spyOn(console, 'error').mockImplementation(() => {})

    renderShellWithBoom()

    await screen.findByText('화면을 표시하지 못했습니다')
    expect(screen.getByRole('link', { name: '대시보드로' })).toBeTruthy()
  })

  it('다른 화면으로 이동하면 오류 화면이 사라진다 — 경계가 경로로 리셋된다', async () => {
    stubServer()
    vi.spyOn(console, 'error').mockImplementation(() => {})

    renderShellWithBoom()
    await screen.findByText('화면을 표시하지 못했습니다')

    /*
     * ⚠️ 이 단언이 `key={pathname}`을 잠근다. key가 없으면 경계가 스스로 리셋되지
     * 않아 **경로가 바뀌어도 오류 화면이 그대로 남는다** — 사용자 입장에서는
     * 백지와 다르지 않다.
     */
    fireEvent.click(
      screen.getByRole('link', { name: new RegExp(SCREEN_BY_ID.VESSEL_MANAGEMENT.label) }),
    )

    expect(await screen.findByText('다른 화면')).toBeTruthy()
    expect(screen.queryByText('화면을 표시하지 못했습니다')).toBeNull()
  })

  it('던지지 않는 화면은 평소대로 그린다', async () => {
    stubServer()

    renderShellWithBoom(MANAGEMENT_PATH)

    expect(await screen.findByText('다른 화면')).toBeTruthy()
    expect(screen.queryByText('화면을 표시하지 못했습니다')).toBeNull()
  })
})

/**
 * 상단바 항차 셀렉트가 **세 상태를 구분**한다 (#824 ⑶).
 *
 * 종전에는 조회가 실패해도 `setVoyages([])`로 떨어져 셀렉트가 **「항차 없음」**을
 * 말했다 — 항차가 1,000건이어도 그렇다. 사용자는 **항차를 만들어야 하는지 서버를
 * 봐야 하는지** 알 수 없다.
 *
 * ⚠️ **같은 파일의 선박 셀렉트는 셋을 정확히 구분한다** — `shellContext.ts`가
 * *「`ready`인데 비었으면 등록된 배가 없는 것이고, `failed`면 서버를 못 읽은 것이다」*
 * 로 그 판단을 적어 두었다. **항차 축에만 대응 필드가 없었다.**
 */
describe('상단바 항차 셀렉트가 조회 실패를 「없음」으로 말하지 않는다 (#824 ⑶)', () => {
  function stubWithVoyages(handler: (url: string) => Response | null) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({ data: { id: 'u1', email: 'a@b.c', display_name: '테스터' } })
        }
        if (url.includes('/vessels') && url.includes('/voyages')) {
          const custom = handler(url)
          if (custom) return custom
          return jsonResponse({ data: [] })
        }
        if (url.includes('/vessels')) return jsonResponse(VESSELS)
        return jsonResponse({ data: [] })
      }),
    )
  }

  it('조회가 실패하면 「불러오지 못했습니다」로 말한다', async () => {
    stubWithVoyages(() => jsonResponse({ error: { message: '서버 오류' } }, 500))

    renderShell()

    expect(await screen.findByText('항차를 불러오지 못했습니다')).toBeTruthy()
    expect(screen.queryByText('항차 없음')).toBeNull()
  })

  it('진짜로 항차가 없으면 종전대로 「항차 없음」이다', async () => {
    stubWithVoyages(() => null)

    renderShell()

    expect(await screen.findByText('항차 없음')).toBeTruthy()
    expect(screen.queryByText('항차를 불러오지 못했습니다')).toBeNull()
  })
})

describe('상단바 알림 버튼 — 알림 체계가 없는 동안은 준비 중이다 (#771 ⑽)', () => {
  it('누를 수 없고, 「읽지 않음 없음」이라고 단정하지 않는다', async () => {
    /*
     * 종전에는 `onClick`이 없는 살아 있는 버튼이었다 — 시연에서 누르면 아무 일도
     * 없고, `aria-label` 「읽지 않음 없음」은 셀 것이 없는 상태를 「없다」로 말했다.
     * `DESIGN_SYSTEM §7.2`의 자리(선박 · 항차 · 알림 · 계정)는 그대로 둔다.
     */
    stubServer()
    renderShell()
    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('ready'))

    const bell = screen.getByRole('button', { name: /알림/ }) as HTMLButtonElement
    expect(bell.disabled).toBe(true)
    expect(bell.getAttribute('aria-label')).toContain('준비 중')
    expect(bell.getAttribute('aria-label')).not.toContain('읽지 않음')
    // §7.2 배치 — 항차 셀렉트 뒤, 계정 앞에 그대로 있다.
    const topbar = bell.closest('.app-shell__topbar')
    expect(topbar).not.toBeNull()
  })
})

/**
 * 역할 2종 (`#672` · `UIFLOW §2.2` 역할 열).
 *
 * 현장직에게 사무직 전용 화면(보고서·함대 감축 계획)은 **「사무직 전용」 뱃지의 비활성
 * 항목**이다 — 숨기지 않는다(`implemented: false`의 「준비 중」과 같은 판단). 사무직에게는
 * 그대로 링크다.
 */
/**
 * 상단바에 **규격 밖 컨트롤이 없다** (`#1422` · `DESIGN_SYSTEM §7.2` 🔒).
 *
 * `§7.2`는 상단바에 두는 것을 「전역 컨텍스트(선박·항차) · 알림 · 계정」으로 닫아
 * 두었는데 테마·한/EN 토글 둘이 그 밖에 있었다. 계정 메뉴 안으로 옮겼다.
 *
 * **자리 하나를 지목하지 않는다.** 「테마 토글이 상단바에 없다」로만 적으면 다음에
 * 새 컨트롤이 같은 자리에 붙을 때 아무것도 걸리지 않는다 — `§16` 항목 17이 겹침
 * 순서에서 적은 구조다. 상단바에 **드러나 있는 선택 컨트롤이 하나도 없는지**를 본다.
 */
describe('상단바가 §7.2 배치를 벗어나지 않는다 (#1422)', () => {
  /*
   * 셸은 캐시된 사용자만 읽으므로(프로브는 `RequireAuth`가 한다) 계정 영역을 보려면
   * `useAuthUser`를 직접 세운다 — 아래 `stubRole`과 같은 이유다.
   */
  function stubUser() {
    vi.spyOn(session, 'useAuthUser').mockReturnValue({
      id: 'u1',
      email: 'a@b.c',
      displayName: '테스터',
      role: 'OFFICE',
      emailVerifiedAt: null,
    })
  }

  it('선택 컨트롤(radiogroup)이 상단바에 드러나 있지 않다', async () => {
    stubUser()
    stubServer()
    const { container } = renderShell()
    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('ready'))

    const topbar = container.querySelector('.app-shell__topbar')
    expect(topbar).not.toBeNull()

    for (const group of topbar!.querySelectorAll('[role="radiogroup"]')) {
      // 계정 패널 **안**이면 규격 안이다 — 밖이면 §7.2가 닫아 둔 자리를 넘은 것이다.
      expect(
        group.closest('[data-testid="account-panel"]'),
        `상단바에 드러난 컨트롤이다: ${group.getAttribute('aria-label') ?? group.className}`,
      ).not.toBeNull()
    }
  })

  it('테마·언어는 계정 메뉴를 열어야 나온다 — 사라진 것이 아니다', async () => {
    stubUser()
    stubServer()
    renderShell()
    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('ready'))

    expect(screen.queryByRole('radiogroup', { name: /화면 테마/ })).toBeNull()

    fireEvent.click(screen.getByTestId('account-trigger'))

    expect(screen.getByRole('radiogroup', { name: /화면 테마/ })).toBeTruthy()
    expect(screen.getByRole('radiogroup', { name: /언어/ })).toBeTruthy()
  })
})

describe('사이드바 — 현장직에게 사무직 전용 화면은 비활성 항목이다 (#672)', () => {
  /*
   * 셸은 캐시된 사용자만 읽는다(프로브는 `RequireAuth`가 한다). 그래서 역할은
   * `useAuthUser`를 직접 세운다 — 위 검사들은 사용자를 세우지 않아 `null`이고,
   * 그때는 잠그지 않는다(실제 앱에서는 셸이 사용자 확인 뒤에만 그려진다).
   */
  function stubRole(role: session.UserRole) {
    vi.spyOn(session, 'useAuthUser').mockReturnValue({
      id: 'u2',
      email: 'crew@b.c',
      displayName: '갑판장',
      role,
      emailVerifiedAt: null,
    })
  }

  it('현장직: 보고서·함대 감축 계획은 링크가 아니고 「사무직 전용」이 붙는다', async () => {
    stubRole('FIELD')
    stubServer()
    renderShell()
    const nav = await screen.findByRole('navigation', { name: '주요 화면' })
    const tags = Array.from(nav.querySelectorAll('.app-shell__nav-tag')).map((el) => el.textContent)
    expect(tags.filter((t) => t === '사무직 전용')).toHaveLength(2)
    for (const id of ['REPORTS', 'FLEET_REDUCTION'] as const) {
      const item = screen.getByText(SCREEN_BY_ID[id].label).closest('li')!
      expect(item.querySelector('a')).toBeNull()
      expect(item.querySelector('[aria-disabled="true"]')).not.toBeNull()
    }
    // 세 역할 모두 쓰는 화면은 그대로 링크다
    const dashboard = screen.getByText(SCREEN_BY_ID.MAINBOARD.label).closest('li')!
    expect(dashboard.querySelector('a')).not.toBeNull()
  })

  it('사무직: 같은 두 화면이 링크다', async () => {
    stubRole('OFFICE')
    stubServer()
    renderShell()
    const nav = await screen.findByRole('navigation', { name: '주요 화면' })
    expect(nav.textContent).not.toContain('사무직 전용')
    for (const id of ['REPORTS', 'FLEET_REDUCTION'] as const) {
      const item = screen.getByText(SCREEN_BY_ID[id].label).closest('li')!
      expect(item.querySelector('a')).not.toBeNull()
    }
  })

  it('관리자: 사무직 전용 화면도 그대로 링크다 — ADMIN은 OFFICE의 상위집합 (#1301)', async () => {
    stubRole('ADMIN')
    stubServer()
    renderShell()
    const nav = await screen.findByRole('navigation', { name: '주요 화면' })
    expect(nav.textContent).not.toContain('사무직 전용')
    for (const id of ['REPORTS', 'FLEET_REDUCTION'] as const) {
      const item = screen.getByText(SCREEN_BY_ID[id].label).closest('li')!
      expect(item.querySelector('a')).not.toBeNull()
    }
  })
})

/**
 * 상단바 선박 셀렉트의 **네 상태** (`#1093` ⑴).
 *
 * `vesselsState`는 `#484`가 이 셀렉트를 위해 만든 값인데 정작 표시에 쓰지 않아,
 * 조회가 실패해도 · 첫 로드 중에도 「선박 없음」이었다. 항차 셀렉트는 `#824` ⑶에서
 * 이미 네 상태를 가른다.
 */
describe('상단바 선박 셀렉트가 실패와 없음을 가른다 (#1093 ⑴)', () => {
  /** 선박 목록만 실패시킨다 — 나머지는 정상이라 셸은 계속 돈다. */
  function stubVesselListFailure() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({
            data: { id: 'u1', email: 'a@b.c', display_name: '테스터', role: 'OFFICE' },
          })
        }
        if (url.includes('/vessels') && url.includes('/voyages')) return jsonResponse({ data: [] })
        if (url.includes('/vessels')) return jsonResponse({ error: { message: '서버 오류' } }, 500)
        return jsonResponse({ data: [] })
      }),
    )
  }

  function vesselSelect(): HTMLSelectElement {
    return screen.getByLabelText('선박') as HTMLSelectElement
  }

  it('조회 실패를 「선박 없음」으로 말하지 않는다', async () => {
    stubVesselListFailure()
    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('failed'))
    expect(vesselSelect().textContent).toContain('선박 목록을 불러오지 못했습니다')
    expect(vesselSelect().textContent).not.toContain('선박 없음')
  })

  it('진짜로 0척이면 「선박 없음」이다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({
            data: { id: 'u1', email: 'a@b.c', display_name: '테스터', role: 'OFFICE' },
          })
        }
        return jsonResponse({ data: [] })
      }),
    )
    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessels-state').textContent).toBe('ready'))
    expect(vesselSelect().textContent).toContain('선박 없음')
    expect(vesselSelect().textContent).not.toContain('불러오지 못했습니다')
  })

  it('목록이 오면 「선박 선택 안 함」이고 셀렉트가 열린다', async () => {
    stubServer()
    renderShell()

    await waitFor(() => expect(screen.getByTestId('vessel-count').textContent).toBe('2'))
    expect(vesselSelect().textContent).toContain('선박 선택 안 함')
    expect(vesselSelect().disabled).toBe(false)
  })
})


/** 셸이 준 `refreshVessels`를 눌러 볼 수 있는 자식. */
function RefreshProbe() {
  const context = useShellContext()
  return (
    <button type="button" onClick={() => context.refreshVessels()}>
      목록 다시 부르기
    </button>
  )
}

function renderShellWithProbe() {
  return render(
    <MemoryRouter initialEntries={[FORECAST_PATH]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path={FORECAST_PATH} element={<RefreshProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('선박 목록 다시 부르기 (#1643)', () => {
  it('refreshVessels를 부르면 목록을 한 번 더 조회한다 — 등록·수정 뒤 선택기가 낡지 않게', async () => {
    const calls = stubServer()
    renderShellWithProbe()

    const listCalls = () =>
      calls.filter((url) => url.includes('/vessels') && !url.includes('/voyages')).length
    await waitFor(() => expect(listCalls()).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: '목록 다시 부르기' }))

    await waitFor(() => expect(listCalls()).toBe(2))
  })
})

/**
 * #1812 — 상단바 항차 선택지의 구간이 저장 코드(`BUSAN`)가 아니라 보이는 이름(`부산`)으로
 * 나온다. `voyageCatalog.ts`가 서버 원본(`departure_port_name`·`arrival_port_name`, 저장
 * 코드)에서 선택지를 만드는데, 항차 번호가 없는 항차는 그 코드로 구간을 대신했었다.
 *
 * ## 재작업 — 조회는 항구 목록과 무관하다
 *
 * 처음에는 `AppShell.tsx`의 항차 조회 effect가 `samplePorts`에 의존해, 항구 목록이
 * 늦게 도착할 때마다 항차를 **다시 조회**했다. 그러면 셀렉트가 매번 비었다 다시
 * 차고(깜빡임), `GET /vessels/{id}/voyages`가 두 번 나간다 — 리뷰로 지적돼 되돌렸다.
 * 지금은 `voyageOptionLabel`이 **그릴 때** 저장 코드를 이름으로 바꾸므로, 조회는
 * 한 번만 돈다.
 */
describe('상단바 항차 선택지의 항구 이름 (#1812)', () => {
  // 단언이 픽스처 값을 그대로 쓴다 (#1836 · `AGENTS §4.6`) — 리터럴을 따로 적지 않는다.
  const SAMPLE_PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  function stubServerWithPortCodedVoyage() {
    const voyageCalls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({
            data: { id: 'u1', email: 'a@b.c', display_name: '테스터', role: 'OFFICE' },
          })
        }
        if (url.includes('/ports/samples')) return jsonResponse({ data: SAMPLE_PORTS })
        if (url.includes('/vessels') && url.includes('/voyages')) {
          voyageCalls.push(url)
          return jsonResponse({
            data: [
              {
                id: 'v-1',
                voyage_no: null,
                status: 'PLANNED',
                departure_port_name: 'BUSAN',
                arrival_port_name: 'SINGAPORE',
              },
            ],
          })
        }
        if (url.includes('/vessels')) return jsonResponse(VESSELS)
        return jsonResponse({ data: [] })
      }),
    )
    return voyageCalls
  }

  it('항차 번호가 없어 구간으로 대신할 때, 저장 코드가 그대로 노출되지 않는다', async () => {
    stubServerWithPortCodedVoyage()
    renderShell()

    // 항구 목록은 비동기로 늦게 온다 — 도착하면 이미 그려진 옵션이 보이는 이름으로
    // 다시 그려진다(항차 재조회 없이, `samplePorts` 상태 변화에 따른 리렌더만으로).
    await waitFor(() => {
      const select = document.getElementById('global-voyage') as HTMLSelectElement
      const optionLabel = [...select.querySelectorAll('option')]
        .map((o) => o.textContent)
        .find((text) => text?.includes('→'))
      // 부정 단언만 두면 구간이 통째로 빠져도 통과한다 (#1836) — 픽스처의 보이는 이름도 본다.
      expect(optionLabel).not.toContain(SAMPLE_PORTS[0].name)
      expect(optionLabel).toContain(SAMPLE_PORTS[0].name_ko)
    })
  })

  // #1812 재작업 — 항구 목록이 항차 목록보다 늦게 도착해도 항차 조회는 한 번만 나간다.
  it('항구 목록이 늦게 도착해도 항차 목록을 다시 조회하지 않는다', async () => {
    const voyageCalls = stubServerWithPortCodedVoyage()
    renderShell()

    // 보이는 이름으로 바뀔 때까지 기다린 뒤에도 조회는 한 번뿐이어야 한다.
    await waitFor(() => {
      const select = document.getElementById('global-voyage') as HTMLSelectElement
      const optionLabel = [...select.querySelectorAll('option')]
        .map((o) => o.textContent)
        .find((text) => text?.includes('→'))
      // 부정 단언만 두면 구간이 통째로 빠져도 통과한다 (#1836) — 픽스처의 보이는 이름도 본다.
      expect(optionLabel).not.toContain(SAMPLE_PORTS[0].name)
      expect(optionLabel).toContain(SAMPLE_PORTS[0].name_ko)
    })
    expect(voyageCalls).toHaveLength(1)
  })
})
