// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { RequireAuth } from './RequireAuth'

/**
 * 확인 전에는 로그인으로 보내지 않는다 (#825 ⑴).
 *
 * ## 무엇이 문제였나
 *
 * 첫 렌더에서 `currentUser`는 **언제나 `null`**이고 프로브는 `useEffect`라 커밋
 * **이후**에 돈다. 그 한 프레임 때문에 로그인 상태로 새로고침할 때마다 주소가
 * `/login?next=…`로 바뀌며 **로그인 카드가 그려졌다가 되돌아왔다.**
 *
 * ⚠️ **문서화된 동작이 구현되지 않은 상태였다** — `RequireAuth`의 주석이 이미
 * *「확인 중에는 자식을 렌더하지 않되 레이아웃을 유지한다 — 깜빡임으로 로그인 화면을
 * 잠깐 보여주는 것보다 낫다」*를 규정하고 있었다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const ME_OK = jsonResponse({
  data: { id: 'u-1', email: 'captain@example.com', display_name: '김선장' },
})

function renderGuard(path = '/vessels/v-1#fleet-actions') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/vessels/:id"
          element={
            <RequireAuth>
              <p>보호된 화면</p>
            </RequireAuth>
          }
        />
        <Route path="/login" element={<p data-testid="login-card">로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('세션 확인 전에는 판정하지 않는다 (#825 ⑴)', () => {
  it('확인 중에는 로그인 화면이 그려지지 않는다', async () => {
    let release: ((value: Response) => void) | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Promise<Response>((resolve) => {
            release = resolve
          }),
      ),
    )

    renderGuard()

    // 프로브가 끝나기 전 — 로그인 카드도, 보호된 화면도 없다.
    expect(screen.queryByTestId('login-card')).toBeNull()
    expect(screen.queryByText('보호된 화면')).toBeNull()

    await import('@testing-library/react').then(({ act }) =>
      act(async () => {
        release?.(ME_OK)
      }),
    )
    expect(await screen.findByText('보호된 화면')).toBeTruthy()
    // 끝까지 로그인 화면이 한 번도 나오지 않았다 — 그것이 「깜빡임」의 정체다.
    expect(screen.queryByTestId('login-card')).toBeNull()
  })

  it('확인 결과가 비인증이면 그때 보낸다 — fail-closed는 그대로다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(null, 401)))

    renderGuard()

    expect(await screen.findByTestId('login-card')).toBeTruthy()
  })

  it('네트워크 실패도 비인증으로 취급한다 — 확인 안 됨을 열어 두지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    renderGuard()

    expect(await screen.findByTestId('login-card')).toBeTruthy()
  })
})
