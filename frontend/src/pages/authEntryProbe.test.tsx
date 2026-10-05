// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * 로그인·가입 화면이 세션을 확인한다 (`#2127`).
 *
 * ## 무엇이 문제였나
 *
 * 두 화면은 **캐시된 사용자가 있을 때만** 이동했다. 주소창에 `/login`을 직접 치면 캐시가
 * 비어 있으므로, 세션이 유효한데도 로그인 폼이 그려졌다 — 세션을 묻는 것은 가드
 * (`RequireAuth`)뿐이었고 두 화면은 가드 밖이다.
 *
 * ## 검사마다 모듈을 새로 읽는다
 *
 * 「확인했는가」는 `auth/session.ts`의 모듈 전역이고 **되돌리는 길이 없다**(한 번 확인하면
 * 페이지를 새로 열 때까지 확인된 상태다 — 그것이 맞는 동작이다). 주소창으로 직접 연 상태를
 * 검사마다 만들려면 모듈을 새로 읽어야 한다. React까지 함께 새로 읽히므로 렌더 도구도
 * 같은 묶음에서 가져온다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const ME_OK = jsonResponse({
  data: { id: 'u-1', email: 'captain@example.com', display_name: '김선장' },
})
const ME_401 = jsonResponse({ error: { code: 'UNAUTHORIZED', message: '인증이 필요합니다.' } }, 401)

async function fresh() {
  vi.resetModules()
  const rtl = await import('@testing-library/react')
  const { MemoryRouter, Route, Routes, useLocation } = await import('react-router')
  const { LoginPage } = await import('./LoginPage')
  const { SignupPage } = await import('./SignupPage')
  const { RequireAuth } = await import('../auth/RequireAuth')
  const { DEFAULT_PATH } = await import('../screens')

  function Elsewhere() {
    const location = useLocation()
    return <p data-testid="elsewhere">{`${location.pathname}${location.search}${location.hash}`}</p>
  }

  function open(path: string) {
    return rtl.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route
            path="/guarded"
            element={
              <RequireAuth>
                <p data-testid="guarded">보호된 화면</p>
              </RequireAuth>
            }
          />
          <Route path="*" element={<Elsewhere />} />
        </Routes>
      </MemoryRouter>,
    )
  }
  return { ...rtl, open, DEFAULT_PATH }
}

/** 요청 주소만 모은다 — 세션 확인이 몇 번 나갔는지 센다. */
function stubFetch(impl: () => Promise<Response>) {
  const fetchImpl = vi.fn(async (_url: string) => await impl())
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

const meCalls = (fetchImpl: ReturnType<typeof stubFetch>) =>
  fetchImpl.mock.calls.filter(([url]) => String(url).endsWith('/auth/me')).length

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('로그인 화면 — 유효한 세션이면 폼 대신 이동한다 (#2127)', () => {
  it('복귀 경로가 있으면 그리로 간다', async () => {
    stubFetch(async () => ME_OK)
    const { open, screen, waitFor } = await fresh()

    open('/login?next=' + encodeURIComponent('/vessels/v-1?tab=fuel#top'))

    await waitFor(() =>
      expect(screen.getByTestId('elsewhere').textContent).toBe('/vessels/v-1?tab=fuel#top'),
    )
    expect(screen.queryByTestId('login-submit')).toBeNull()
  })

  it('복귀 경로가 없으면 앱 루트로 간다', async () => {
    stubFetch(async () => ME_OK)
    const { open, screen, waitFor } = await fresh()

    open('/login')

    await waitFor(() => expect(screen.getByTestId('elsewhere').textContent).toBe('/'))
  })

  it('다른 원점으로 읽히는 복귀 경로는 쓰지 않는다', async () => {
    stubFetch(async () => ME_OK)
    const { open, screen, waitFor } = await fresh()

    open('/login?next=' + encodeURIComponent('/\\evil.example.com/x'))

    await waitFor(() => expect(screen.getByTestId('elsewhere').textContent).toBe('/'))
  })

  it('확인하는 동안에는 폼을 그리지 않는다 — 그렸다가 사라지지 않는다', async () => {
    let answer: (response: Response) => void = () => {}
    stubFetch(() => new Promise<Response>((resolve) => (answer = resolve)))
    const { open, screen, waitFor, act } = await fresh()

    const { container } = open('/login')

    expect(screen.queryByTestId('login-submit')).toBeNull()
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()

    await act(async () => answer(ME_OK))
    await waitFor(() => expect(screen.getByTestId('elsewhere')).toBeTruthy())
    // 끝까지 폼은 한 번도 나오지 않았다.
    expect(screen.queryByTestId('login-submit')).toBeNull()
  })
})

describe('로그인 화면 — 확인이 「세션 없음」이나 실패로 끝나면 폼이 나온다 (#2127)', () => {
  it.each<[string, () => Promise<Response>]>([
    ['세션 없음(401)', async () => ME_401],
    ['서버 오류(500)', async () => jsonResponse(null, 500)],
    ['게이트웨이 오류(503)', async () => jsonResponse(null, 503)],
    [
      '통신 오류',
      async () => {
        throw new TypeError('Failed to fetch')
      },
    ],
  ])('%s', async (_label, impl) => {
    stubFetch(impl)
    const { open, screen, waitFor } = await fresh()

    const { container } = open('/login?next=%2Fvessels%2Fv-1')

    // 서버가 죽어 있어도 로그인 화면은 떠야 한다.
    await waitFor(() => expect(screen.getByTestId('login-submit')).toBeTruthy())
    expect(container.querySelector('[aria-busy="true"]')).toBeNull()
    expect(screen.queryByTestId('elsewhere')).toBeNull()
  })
})

describe('가드와 겹치지 않는다 (#2127)', () => {
  it('가드가 비인증으로 판정해 보낸 로그인 화면은 다시 묻지 않는다', async () => {
    const fetchImpl = stubFetch(async () => ME_401)
    const { open, screen, waitFor } = await fresh()

    open('/guarded')

    await waitFor(() => expect(screen.getByTestId('login-submit')).toBeTruthy())
    expect(meCalls(fetchImpl)).toBe(1)
  })

  it('주소창으로 연 로그인 화면이 이동시킨 뒤 가드와 순환하지 않는다', async () => {
    const fetchImpl = stubFetch(async () => ME_OK)
    const { open, screen, waitFor } = await fresh()

    open('/login?next=%2Fguarded')

    await waitFor(() => expect(screen.getByTestId('guarded')).toBeTruthy())
    // 로그인 화면의 확인 한 번 + 가드가 마운트되며 하는 확인 한 번. 그 뒤로 늘지 않는다.
    const settled = meCalls(fetchImpl)
    expect(settled).toBeLessThanOrEqual(2)
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(meCalls(fetchImpl)).toBe(settled)
    expect(screen.getByTestId('guarded')).toBeTruthy()
  })

  it('로그인 화면과 가드가 같은 답을 낸 뒤 세션이 끊기면 로그인 폼에서 멈춘다', async () => {
    // 첫 확인은 유효, 가드의 확인은 401 — 그 사이에 세션이 끝난 경우다.
    let count = 0
    const fetchImpl = stubFetch(async () => (++count === 1 ? ME_OK : ME_401))
    const { open, screen, waitFor } = await fresh()

    open('/login?next=%2Fguarded')

    await waitFor(() => expect(screen.getByTestId('login-submit')).toBeTruthy())
    const settled = meCalls(fetchImpl)
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(meCalls(fetchImpl)).toBe(settled)
  })
})

describe('가입 화면도 같은 확인을 한다 (#2127)', () => {
  it('유효한 세션이면 폼 대신 기본 화면으로 간다', async () => {
    stubFetch(async () => ME_OK)
    const { open, screen, waitFor, DEFAULT_PATH } = await fresh()

    const { container } = open('/signup')

    expect(container.querySelector('button[type="submit"]')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('elsewhere').textContent).toBe(DEFAULT_PATH))
    expect(container.querySelector('button[type="submit"]')).toBeNull()
  })

  it.each<[string, () => Promise<Response>]>([
    ['세션 없음(401)', async () => ME_401],
    ['서버 오류(500)', async () => jsonResponse(null, 500)],
    [
      '통신 오류',
      async () => {
        throw new TypeError('Failed to fetch')
      },
    ],
  ])('%s이면 가입 폼이 나온다', async (_label, impl) => {
    stubFetch(impl)
    const { open, waitFor } = await fresh()

    const { container } = open('/signup')

    await waitFor(() => expect(container.querySelector('button[type="submit"]')).not.toBeNull())
  })
})
