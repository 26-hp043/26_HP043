// @vitest-environment jsdom
import '../test/renderSetup'

import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VerifyEmailPage, resetVerificationRequests } from './VerifyEmailPage'

/**
 * 이메일 인증 화면 (`#1646` · `UIFLOW 0-4` · `API_SPEC §1.2`).
 *
 * 토큰은 **일회용**이라, 효과가 두 번 도는 개발 Strict Mode에서 두 번 소비되면 성공한 인증이
 * 실패로 덮인다. 문구는 리터럴로 단언하지 않는다(`AGENTS §4.6`) — 서버가 준 문자열이 그대로
 * 나오는지와 요청 횟수로 본다.
 */

const fetchMock = vi.fn<typeof fetch>()

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
    fetchMock.mockResolvedValueOnce(ok('[인증 완료 문구]'))
    renderStrict('/verify-email?token=t-1')

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('[인증 완료 문구]'))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('실제로 쓰인 토큰은 그대로 실패 화면이다', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'X', message: '[만료·사용됨 문구]' } }), {
        status: 400,
      }),
    )
    renderStrict('/verify-email?token=used')

    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('[만료·사용됨 문구]'))
  })

  it('실패한 토큰을 다시 열면 다시 시도한다 — 옛 실패를 되살리지 않는다', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: 'X', message: '[연결 실패]' } }), { status: 503 }),
    )
    const first = renderStrict('/verify-email?token=retry')
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    first.unmount()

    fetchMock.mockResolvedValueOnce(ok('[두 번째 시도 성공]'))
    renderStrict('/verify-email?token=retry')
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('[두 번째 시도 성공]'))
  })

  it('토큰이 없으면 아무 요청도 보내지 않는다', () => {
    renderStrict('/verify-email')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
