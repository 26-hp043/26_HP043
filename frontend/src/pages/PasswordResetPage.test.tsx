// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { PasswordResetPage } from './PasswordResetPage'
import { LOGIN_PATH } from '../auth/session'
import { MIN_PASSWORD_LENGTH } from '../features/auth/authRules'

/**
 * 비밀번호 찾기 두 단계 (`#1618` · `UIFLOW 0-3` · `API_SPEC §1.2`).
 *
 * ## 문구를 리터럴로 단언하지 않는다 (`AGENTS §4.6`)
 *
 * 성공 문구는 **서버가 준 것을 그대로** 보이는지만 본다 — 검사가 서버 응답으로 넣은 문자열이
 * 화면에 그대로 나오는가다. 가입 여부를 가르지 않는다는 `PRD §6.3` 규칙은 「화면이 자기
 * 문장을 만들지 않는다」로 단언한다. 나머지는 성질(요청이 나갔는가 · 오류가 칸에 붙었는가 ·
 * 버튼이 다시 눌리는가)로 본다.
 */

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function ok(message: string): Response {
  return new Response(JSON.stringify({ data: { message } }), { status: 200 })
}

function fail(status: number, message: string, details?: Array<{ field: string; message: string }>) {
  return new Response(JSON.stringify({ error: { code: 'X', message, details } }), { status })
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/password-reset" element={<PasswordResetPage />} />
        <Route path={LOGIN_PATH} element={<p data-testid="login-screen">login</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

function bodyOf(call: number): Record<string, unknown> {
  return JSON.parse(String(fetchMock.mock.calls[call][1]?.body))
}

describe('⑴ 재설정 메일 요청 — 토큰 없음', () => {
  it('빈 값·잘못된 이메일은 요청을 보내지 않고 칸에 오류를 붙인다', () => {
    renderAt('/password-reset')
    fireEvent.click(screen.getByTestId('reset-request-submit'))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByLabelText('이메일').getAttribute('aria-invalid')).toBe('true')

    type('이메일', 'not-an-email')
    fireEvent.click(screen.getByTestId('reset-request-submit'))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('성공하면 서버 문구를 그대로 보이고, 화면이 가입 여부를 가르는 문장을 만들지 않는다', async () => {
    const serverSays = '[서버 문구] 입력하신 주소로 안내를 보냈습니다.'
    fetchMock.mockResolvedValueOnce(ok(serverSays))
    renderAt('/password-reset')
    type('이메일', 'user@example.com')
    fireEvent.click(screen.getByTestId('reset-request-submit'))

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(serverSays))
    expect(bodyOf(0)).toEqual({ email: 'user@example.com' })
    // 성공 뒤에는 폼이 사라진다 — 같은 주소로 계속 누르게 두지 않는다.
    expect(screen.queryByTestId('reset-request-submit')).toBeNull()
  })

  it('실패하면 오류가 보이고 버튼이 다시 눌린다', async () => {
    fetchMock.mockResolvedValueOnce(fail(500, '[서버 오류 문구]'))
    renderAt('/password-reset')
    type('이메일', 'user@example.com')
    fireEvent.click(screen.getByTestId('reset-request-submit'))

    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('[서버 오류 문구]'))
    const button = screen.getByTestId('reset-request-submit') as HTMLButtonElement
    expect(button.disabled).toBe(false)

    fetchMock.mockResolvedValueOnce(ok('[두 번째]'))
    fireEvent.click(button)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})

describe('⑵ 새 비밀번호 설정 — `?token=`', () => {
  it('짧은 비밀번호·확인 불일치는 요청 전에 막는다', () => {
    renderAt('/password-reset?token=abc')
    type('새 비밀번호', 'x'.repeat(MIN_PASSWORD_LENGTH - 1))
    type('새 비밀번호 확인', 'x'.repeat(MIN_PASSWORD_LENGTH - 1))
    fireEvent.click(screen.getByTestId('reset-confirm-submit'))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByLabelText('새 비밀번호').getAttribute('aria-invalid')).toBe('true')

    type('새 비밀번호', 'y'.repeat(MIN_PASSWORD_LENGTH))
    type('새 비밀번호 확인', 'z'.repeat(MIN_PASSWORD_LENGTH))
    fireEvent.click(screen.getByTestId('reset-confirm-submit'))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByLabelText('새 비밀번호 확인').getAttribute('aria-invalid')).toBe('true')
  })

  it('만료·사용된 링크의 오류는 칸이 없어 폼 위에 보인다 (#877 ⑴)', async () => {
    fetchMock.mockResolvedValueOnce(
      fail(400, '[만료 문구]', [{ field: 'token', message: '[만료 문구]' }]),
    )
    renderAt('/password-reset?token=expired')
    type('새 비밀번호', 'p'.repeat(MIN_PASSWORD_LENGTH))
    type('새 비밀번호 확인', 'p'.repeat(MIN_PASSWORD_LENGTH))
    fireEvent.click(screen.getByTestId('reset-confirm-submit'))

    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('[만료 문구]'))
    expect(bodyOf(0)).toEqual({ token: 'expired', password: 'p'.repeat(MIN_PASSWORD_LENGTH) })
  })

  it('비밀번호 규칙 오류는 그 칸에 붙는다', async () => {
    fetchMock.mockResolvedValueOnce(
      fail(422, '입력값 오류', [{ field: 'password', message: '[칸 문구]' }]),
    )
    renderAt('/password-reset?token=abc')
    type('새 비밀번호', 'p'.repeat(MIN_PASSWORD_LENGTH))
    type('새 비밀번호 확인', 'p'.repeat(MIN_PASSWORD_LENGTH))
    fireEvent.click(screen.getByTestId('reset-confirm-submit'))

    await waitFor(() =>
      expect(screen.getByLabelText('새 비밀번호').getAttribute('aria-invalid')).toBe('true'),
    )
  })

  it('성공하면 서버 문구를 보이고 버튼으로 로그인에 돌아간다', async () => {
    fetchMock.mockResolvedValueOnce(ok('[변경 완료 문구]'))
    renderAt('/password-reset?token=abc')
    type('새 비밀번호', 'p'.repeat(MIN_PASSWORD_LENGTH))
    type('새 비밀번호 확인', 'p'.repeat(MIN_PASSWORD_LENGTH))
    fireEvent.click(screen.getByTestId('reset-confirm-submit'))

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('[변경 완료 문구]'))
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByTestId('login-screen')).toBeTruthy()
  })
})
