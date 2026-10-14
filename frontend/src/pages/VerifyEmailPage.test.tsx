// @vitest-environment jsdom
import '../test/renderSetup'

import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VerifyEmailPage } from './VerifyEmailPage'
import { resetVerificationRequests } from './verifyEmailRequests'

/**
 * 이메일 인증 화면 (`#1646` · `UIFLOW 0-4` · `API_SPEC §1.2`).
 *
 * 토큰은 **일회용**이라, 효과가 두 번 도는 개발 Strict Mode에서 두 번 소비되면 성공한 인증이
 * 실패로 덮인다. 문구는 리터럴로 단언하지 않는다(`AGENTS §4.6`) — 서버가 준 문자열이 그대로
 * 나오는지와 요청 횟수로 본다.
 *
 * 인증 확인은 그 계정으로 로그인한 세션에서만 보낸다(`#2327`). 그래서 세션 확인
 * (`GET /auth/me`)은 로그인된 사용자로 답하고, 셈은 인증 확인 요청만 센다.
 */

const fetchMock = vi.fn<typeof fetch>()

const ME_URL_TAIL = '/auth/me'

function meOk() {
  return new Response(
    JSON.stringify({ data: { id: 'u-1', email: 'captain@example.com', display_name: null } }),
    { status: 200 },
  )
}

/** 세션 확인은 로그인 상태로 답하고, 그 밖의 요청은 `confirm`이 답한다. */
function routeFetch(confirm: () => Promise<Response>) {
  fetchMock.mockImplementation(async (input) =>
    String(input).endsWith(ME_URL_TAIL) ? meOk() : await confirm(),
  )
}

const confirmCalls = () =>
  fetchMock.mock.calls.filter(([url]) => !String(url).endsWith(ME_URL_TAIL)).length

beforeEach(() => {
  fetchMock.mockReset()
  resetVerificationRequests()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetVerificationRequests()
})

function renderStrict(url: string) {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/verify-email" element={<VerifyEmailPage />} />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  )
}

function ok(message: string) {
  return new Response(JSON.stringify({ data: { message } }), { status: 200 })
}

describe('Strict Mode에서도 토큰을 한 번만 쓴다 (#1646)', () => {
  it('효과가 두 번 돌아도 요청은 한 번이고 성공 화면이 남는다', async () => {
    routeFetch(async () => ok('[인증 완료 문구]'))
    renderStrict('/verify-email?token=t-1')

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('[인증 완료 문구]'))
    expect(confirmCalls()).toBe(1)
  })

  it('실제로 쓰인 토큰은 그대로 실패 화면이다', async () => {
    routeFetch(
      async () =>
        new Response(JSON.stringify({ error: { code: 'X', message: '[만료·사용됨 문구]' } }), {
          status: 400,
        }),
    )
    renderStrict('/verify-email?token=used')

    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('[만료·사용됨 문구]'))
  })

  it('실패한 토큰을 다시 열면 다시 시도한다 — 옛 실패를 되살리지 않는다', async () => {
    routeFetch(
      async () =>
        new Response(JSON.stringify({ error: { code: 'X', message: '[연결 실패]' } }), {
          status: 503,
        }),
    )
    const first = renderStrict('/verify-email?token=retry')
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    first.unmount()

    routeFetch(async () => ok('[두 번째 시도 성공]'))
    renderStrict('/verify-email?token=retry')
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('[두 번째 시도 성공]'))
  })

  it('토큰이 없으면 아무 요청도 보내지 않는다', () => {
    renderStrict('/verify-email')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('로그인한 세션에서만 토큰을 보낸다 (#2327)', () => {
  /*
   * 「세션을 확인했는가」는 `auth/session.ts`의 모듈 전역이라 되돌리는 길이 없다. 확인 전
   * 상태(주소창으로 링크를 연 브라우저)를 만들려면 모듈을 새로 읽는다 — `authEntryProbe.test.tsx`와
   * 같은 방식이다. React까지 새로 읽히므로 렌더 도구도 같은 묶음에서 가져온다.
   */
  async function fresh() {
    vi.resetModules()
    const rtl = await import('@testing-library/react')
    const router = await import('react-router')
    const { VerifyEmailPage: Page } = await import('./VerifyEmailPage')

    function Login() {
      const location = router.useLocation()
      return <p data-testid="login">{location.search}</p>
    }

    rtl.render(
      <router.MemoryRouter initialEntries={['/verify-email?token=owner-token']}>
        <router.Routes>
          <router.Route path="/verify-email" element={<Page />} />
          <router.Route path="/login" element={<Login />} />
        </router.Routes>
      </router.MemoryRouter>,
    )
    return rtl
  }

  it('세션이 없으면 토큰을 보내지 않고, 토큰째 돌아올 주소를 달고 로그인으로 간다', async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith(ME_URL_TAIL)
        ? new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'x' } }), {
            status: 401,
          })
        : ok('[보내면 안 된다]'),
    )
    const rtl = await fresh()

    const login = await rtl.screen.findByTestId('login')
    const next = new URLSearchParams(login.textContent ?? '').get('next')
    expect(next).toBe('/verify-email?token=owner-token')
    expect(confirmCalls()).toBe(0)
  })

  it('세션이 있으면 그 세션으로 한 번 보낸다', async () => {
    routeFetch(async () => ok('[인증 완료 문구]'))
    const rtl = await fresh()

    await rtl.waitFor(() =>
      expect(rtl.screen.getByRole('status').textContent).toBe('[인증 완료 문구]'),
    )
    expect(confirmCalls()).toBe(1)
  })
})
