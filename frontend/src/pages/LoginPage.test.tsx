// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { LoginPage } from './LoginPage'
import { probeCurrentUser } from '../auth/session'

/**
 * 로그인 화면의 둘러보기 링크 (`#1486`).
 *
 * 백엔드는 `POST /auth/tour-login`이 `login()`과 **같은 성공 계약**(사용자 봉투 +
 * 세션 쿠키)을 쓰고, 실패는 항상 `422`에 정본 문구 하나로 응답한다(「꺼져 있음」과
 * 「코드 불일치」를 구분하지 않는다). 이 파일이 보는 것은 그 계약을 화면이 어떻게
 * 쓰는가다 — 버튼의 **존재 자체가 기능을 알리므로** `?tour=` 코드가 없을 때 버튼이
 * 렌더되지 않는 것부터 먼저 잠근다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

afterEach(async () => {
  /*
   * `session.ts`의 사용자 캐시는 모듈 전역이다 — 성공 테스트가 로그인 상태를
   * 남기면 다음 테스트의 `LoginPage`가 즉시 `<Navigate>`로 빠져나간다
   * (`session.test.ts`와 같은 이유로 각 테스트가 스스로 초기화한다).
   */
  await probeCurrentUser(async () => ({ ok: false, status: 401, json: async () => null }) as Response)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('둘러보기 링크 (#1486)', () => {
  it('?tour= 도 없고 공개 스위치도 꺼져 있으면 버튼이 렌더되지 않는다', () => {
    vi.stubEnv('VITE_TOUR_PUBLIC', '')
    render(
      <MemoryRouter initialEntries={['/login']}>
        <LoginPage />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('tour-submit')).toBeNull()
  })

  /*
   * 공개 둘러보기 (#1486 후속).
   *
   * 링크 없이도 들어올 수 있어야 하지만, **코드가 번들에 실리면 안 된다** — 그래서 화면이
   * 읽는 것은 불리언 하나이고, 호출은 코드 없이 나간다(서버의 `TOUR_PUBLIC`이 판정).
   */
  it('공개 스위치가 켜져 있으면 코드 없이도 버튼이 보이고 빈 코드로 서버를 부른다', async () => {
    vi.stubEnv('VITE_TOUR_PUBLIC', 'true')
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: { id: 'u1', email: 'tour@bluelog.local', display_name: '둘러보기' } }),
    )
    vi.stubGlobal('fetch', fetchImpl)

    render(
      <MemoryRouter initialEntries={['/login']}>
        <LoginPage />
      </MemoryRouter>,
    )

    const button = screen.getByTestId('tour-submit')
    fireEvent.click(button)

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled())
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({ code: '' })
  })

  it('?tour=abc 가 있으면 버튼이 보이고, 누르면 tourLogin이 그 코드로 서버를 부른다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: { id: 'u1', email: 'tour@example.com', display_name: null } }),
    )
    vi.stubGlobal('fetch', fetchImpl)

    render(
      <MemoryRouter initialEntries={['/login?tour=abc']}>
        <LoginPage />
      </MemoryRouter>,
    )

    const button = screen.getByTestId('tour-submit')
    expect(button).not.toBeNull()
    fireEvent.click(button)

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/auth/tour-login')
    expect(JSON.parse(String(init.body))).toEqual({ code: 'abc' })
  })

  it('실패하면 서버 문구가 화면에 그대로 나온다 — 프런트가 새로 짓지 않는다', async () => {
    // 정본 문구 (백엔드 `POST /auth/tour-login` 계약) — 바꾸려면 그 계약 개정이 먼저다.
    const message = '둘러보기 링크가 올바르지 않습니다. 받으신 링크를 다시 확인해 주세요.'
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: 'VALIDATION_ERROR', message } }, 422),
    )
    vi.stubGlobal('fetch', fetchImpl)

    render(
      <MemoryRouter initialEntries={['/login?tour=bad-code']}>
        <LoginPage />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByTestId('tour-submit'))

    await waitFor(() => expect(screen.getByText(message)).not.toBeNull())
  })
})
