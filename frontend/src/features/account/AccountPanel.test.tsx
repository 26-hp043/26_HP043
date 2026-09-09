// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AccountPanel } from './AccountPanel'
import { WITHDRAWAL_NOTICE } from '../auth/authRules'
import * as session from '../../auth/session'

/**
 * 탈퇴 화면 (`PRD §5.1` MUST · `#754`).
 *
 * ## 무엇이 문제였나
 *
 * 서버(`DELETE /auth/me`)·정본(`API_SPEC §1.2`·`§12`·`PRD §5.1`·`§6.3`)·`UIFLOW 2-6`이
 * 전부 갖춰졌는데 **화면만 없었다.** `PRD §6.3`이 원문을 확정한 탈퇴 문구를 쓰는 코드가
 * 저장소에 **한 곳도 없었다.**
 *
 * 그 사이 **이메일을 바꿀 유일한 경로가 막혀 있었다** — 같은 화면의 「계정 정보」 절이
 * *「다른 주소를 쓰려면 탈퇴 후 다시 가입해 주세요」*라고 안내하는데 탈퇴할 수가 없었다.
 */

function stubUser() {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'demo@bluelog.local',
    displayName: '테스터',
  } as ReturnType<typeof session.useAuthUser>)
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <AccountPanel />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('탈퇴 절이 존재한다 (#754)', () => {
  it('설정 화면에 탈퇴 버튼이 있다', () => {
    stubUser()
    renderPanel()

    // 종전에는 이 버튼이 없었다 — 서버·정본은 다 있는데 화면만 없었다.
    expect(screen.getByRole('button', { name: '탈퇴하기' })).toBeTruthy()
  })

  it('`PRD §6.3` 문구가 **그대로** 나온다', () => {
    stubUser()
    renderPanel()

    /*
     * 정본이 원문을 확정한 문구다(`AGENTS §4.6`). 화면이 새로 적으면 안 된다 —
     * 실제로 종전에는 이 문구의 소비처가 0이라, 다음에 화면을 만드는 사람이
     * 찾지 못하고 새로 적을 여지가 있었다.
     */
    expect(screen.getByText(WITHDRAWAL_NOTICE)).toBeTruthy()
  })

  it('세 사실을 모두 알린다 — 로그인 불가 · 기록 보존 · 재가입 가능', () => {
    stubUser()
    renderPanel()

    const notice = screen.getByText(WITHDRAWAL_NOTICE).textContent ?? ''
    expect(notice).toContain('로그인할 수 없습니다')
    expect(notice).toContain('보존되며')
    // 이메일을 바꿀 유일한 경로이므로 이 문장이 특히 중요하다.
    expect(notice).toContain('같은 이메일로 다시 가입할 수 있습니다')
  })
})

describe('되돌릴 수 없는 조작이라 확인을 받는다 (#754)', () => {
  it('버튼 한 번으로는 탈퇴하지 않는다', () => {
    stubUser()
    const call = vi.spyOn(session, 'deleteAccount').mockResolvedValue(undefined)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }))

    // 오조작이 곧 계정 삭제가 되면 안 된다.
    expect(call).not.toHaveBeenCalled()
    expect(screen.getByText('정말 탈퇴하시겠습니까?')).toBeTruthy()
  })

  it('확인 단계에서 취소할 수 있다', () => {
    stubUser()
    const call = vi.spyOn(session, 'deleteAccount').mockResolvedValue(undefined)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }))
    fireEvent.click(screen.getByRole('button', { name: '취소' }))

    expect(call).not.toHaveBeenCalled()
    expect(screen.queryByText('정말 탈퇴하시겠습니까?')).toBeNull()
    expect(screen.getByRole('button', { name: '탈퇴하기' })).toBeTruthy()
  })

  it('확인하면 `DELETE /auth/me`를 부른다', async () => {
    stubUser()
    const call = vi.spyOn(session, 'deleteAccount').mockResolvedValue(undefined)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }))
    fireEvent.click(screen.getByRole('button', { name: '탈퇴합니다' }))

    await waitFor(() => expect(call).toHaveBeenCalledTimes(1))
  })
})

describe('실패는 화면에 남는다 — 탈퇴된 척하지 않는다 (#754)', () => {
  it('서버가 거부하면 사유를 보여 주고 화면에 머문다', async () => {
    stubUser()
    vi.spyOn(session, 'deleteAccount').mockRejectedValue(
      new session.AuthRequestError('세션이 만료되었습니다.', 401),
    )
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }))
    fireEvent.click(screen.getByRole('button', { name: '탈퇴합니다' }))

    /*
     * `logout`은 실패해도 이동한다(로그아웃 버튼에 갇히는 것이 최악이므로).
     * 탈퇴는 반대다 — 실패한 채 로그인 화면으로 보내면 사용자는 **탈퇴됐다고 믿는데
     * 계정이 살아 있다.**
     */
    expect(await screen.findByText('세션이 만료되었습니다.')).toBeTruthy()
    expect(screen.getByRole('button', { name: '탈퇴합니다' })).toBeTruthy()
  })

  it('실패 뒤 다시 시도할 수 있다 — 버튼이 잠기지 않는다', async () => {
    stubUser()
    const call = vi
      .spyOn(session, 'deleteAccount')
      .mockRejectedValueOnce(new session.AuthRequestError('일시적 오류', 500))
      .mockResolvedValueOnce(undefined)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }))
    fireEvent.click(screen.getByRole('button', { name: '탈퇴합니다' }))
    await screen.findByText('일시적 오류')

    fireEvent.click(screen.getByRole('button', { name: '탈퇴합니다' }))
    await waitFor(() => expect(call).toHaveBeenCalledTimes(2))
  })
})
