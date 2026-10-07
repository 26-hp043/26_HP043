// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AccountPanel } from './AccountPanel'
import { RegulationParametersSection } from '../parameters/RegulationParametersSection'
import { visibleSections } from '../../pages/settingsSections'
import { ROLE_LABEL, WITHDRAWAL_NOTICE } from '../auth/authRules'
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

function stubUser(role: session.UserRole = 'FIELD', hasAvatar = false) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'demo@bluelog.local',
    displayName: '테스터',
    role,
    emailVerifiedAt: null,
    hasAvatar,
  })
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

/**
 * 서버가 짚은 칸에 오류를 붙인다 (#877 ⑴).
 *
 * 종전에는 서버 문구를 폼 아래 한 줄로만 보였다 — 세 칸 중 어느 것이 틀렸는지 사용자가
 * 추측해야 했다.
 */
describe('비밀번호 변경 — 서버 필드 오류 (#877)', () => {
  it('새 비밀번호를 짚은 422는 그 칸 아래에 뜨고 폼 아래 문구는 없다', async () => {
    stubUser()
    vi.spyOn(session, 'changePassword').mockRejectedValue(
      new session.AuthRequestError('새 비밀번호는 128자 이하여야 합니다.', 422, {
        new_password: '새 비밀번호는 128자 이하여야 합니다.',
      }),
    )
    renderPanel()

    fireEvent.change(screen.getByLabelText('현재 비밀번호'), { target: { value: 'current-pass-1' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'new-pass-long-1' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호 확인'), { target: { value: 'new-pass-long-1' } })
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 바꾸기' }))

    const input = await screen.findByLabelText('새 비밀번호')
    await waitFor(() => expect(input.getAttribute('aria-invalid')).toBe('true'))
    expect(document.getElementById('acc-new-error')?.textContent).toBe(
      '새 비밀번호는 128자 이하여야 합니다.',
    )
    expect(screen.getByLabelText('현재 비밀번호').getAttribute('aria-invalid')).toBeNull()
    // 폼 아래 문구로 한 번 더 뜨지 않는다 — 같은 문구가 두 곳에 있으면 어느 쪽이 원인인지 흐려진다.
    expect(screen.getAllByText('새 비밀번호는 128자 이하여야 합니다.')).toHaveLength(1)
  })
})

/**
 * 역할 3종 (`#672` · `#1301` · `UIFLOW 2-6`).
 *
 * 계정 정보에 자기 역할이 보이고, **관리자에게만** 「계정 · 역할」 절이 있다 — `#1301`로
 * 계정 관리가 업무 권한(사무직)에서 떨어져 나왔다. 역할 변경은 셀렉트 한 번이 곧 저장이고,
 * 마지막 관리자 강등처럼 서버가 거절하면 **서버 문구를 그대로** 보인다 — 판정은 행을
 * 잠근 서버 한 곳이 한다.
 */
describe('역할 — 계정 정보와 역할 지정 절 (#672 · #1301)', () => {
  it('현장직은 자기 역할을 보되 역할 지정 절은 없다', () => {
    stubUser('FIELD')
    renderPanel()
    expect(screen.getByTestId('acc-role').textContent).toBe('현장직')
    expect(screen.queryByRole('region', { name: '계정 · 역할' })).toBeNull()
    expect(session.listUsers).toBeDefined()
  })

  it('사무직도 자기 역할만 보고 역할 지정 절은 못 본다 — 계정 관리는 관리자 전용 (#1301)', () => {
    stubUser('OFFICE')
    renderPanel()
    expect(screen.getByTestId('acc-role').textContent).toBe('사무직')
    expect(screen.queryByRole('region', { name: '계정 · 역할' })).toBeNull()
  })

  it('관리자는 계정 목록을 받아 셀렉트로 역할을 바꾼다 — 선택지는 3종', async () => {
    stubUser('ADMIN')
    const rows: session.CurrentUser[] = [
      { id: 'u-1', email: 'demo@bluelog.local', displayName: '테스터', role: 'ADMIN', emailVerifiedAt: null, hasAvatar: false },
      { id: 'u-2', email: 'crew@bluelog.local', displayName: null, role: 'FIELD', emailVerifiedAt: null, hasAvatar: false },
    ]
    vi.spyOn(session, 'listUsers').mockResolvedValue(rows)
    const update = vi
      .spyOn(session, 'updateUserRole')
      .mockResolvedValue({ ...rows[1], role: 'OFFICE' })
    renderPanel()

    expect(screen.getByTestId('acc-role').textContent).toBe('관리자')
    const select = (await screen.findByLabelText(/crew@bluelog.local/)) as HTMLSelectElement
    expect(select.value).toBe('FIELD')
    // 선택지가 3종이다 — 현장직·사무직·관리자를 모두 지정할 수 있다.
    const optionValues = Array.from(select.options).map((option) => option.value)
    expect(optionValues).toEqual(['OFFICE', 'FIELD', 'ADMIN'])
    // 「(나)」 표시 — 자기 행을 알아본다
    expect(screen.getByLabelText(/demo@bluelog.local \(나\)/)).toBeTruthy()

    fireEvent.change(select, { target: { value: 'OFFICE' } })
    await waitFor(() => expect(update).toHaveBeenCalledWith('u-2', 'OFFICE'))
    await waitFor(() => expect(select.value).toBe('OFFICE'))
    expect(screen.getByRole('status').textContent).toContain('사무직')
  })

  it('서버가 거절하면(마지막 관리자 409) 문구를 그대로 보이고 셀렉트는 원래 값이다', async () => {
    stubUser('ADMIN')
    const rows: session.CurrentUser[] = [
      { id: 'u-1', email: 'demo@bluelog.local', displayName: '테스터', role: 'ADMIN', emailVerifiedAt: null, hasAvatar: false },
    ]
    vi.spyOn(session, 'listUsers').mockResolvedValue(rows)
    const message = '마지막 관리자 계정은 탈퇴하거나 다른 역할로 바꿀 수 없습니다. 다른 계정을 먼저 관리자로 지정해 주세요.'
    vi.spyOn(session, 'updateUserRole').mockRejectedValue(new session.AuthRequestError(message, 409))
    renderPanel()

    const select = (await screen.findByLabelText(/demo@bluelog.local/)) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'FIELD' } })
    await waitFor(() => expect(screen.getByText(message)).toBeTruthy())
    expect(select.value).toBe('ADMIN')
  })

  it('둘러보기 계정 행은 역할을 바꿀 수 없고 다른 행은 바꿀 수 있다 (#2291)', async () => {
    stubUser('ADMIN')
    const rows: session.CurrentUser[] = [
      { id: 'u-1', email: 'demo@bluelog.local', displayName: '테스터', role: 'ADMIN', emailVerifiedAt: null, hasAvatar: false },
      { id: 'u-2', email: 'crew@bluelog.local', displayName: null, role: 'FIELD', emailVerifiedAt: null, hasAvatar: false },
      { id: 'u-t', email: 'tour@bluelog.local', displayName: null, role: 'ADMIN', emailVerifiedAt: null, hasAvatar: false, isTour: true },
    ]
    vi.spyOn(session, 'listUsers').mockResolvedValue(rows)
    const update = vi.spyOn(session, 'updateUserRole')
    renderPanel()

    // 다른 행은 선택 상자가 있다
    expect(await screen.findByLabelText(/crew@bluelog.local/)).toBeTruthy()
    // 둘러보기 행은 선택 상자가 없다 — 이메일을 라벨로 하는 조작 요소가 하나도 없다
    expect(screen.queryByLabelText(/tour@bluelog.local/)).toBeNull()
    const row = screen.getByTestId('acc-tour-u-t')
    expect(row.querySelector('select')).toBeNull()
    // 까닭이 글자로 있고(낭독기가 읽는다), 역할 자리는 「관리자」가 아닌 값이다
    expect(row.textContent).toContain('tour@bluelog.local')
    expect(row.textContent).not.toContain(ROLE_LABEL.ADMIN)
    expect(row.textContent!.length).toBeGreaterThan('tour@bluelog.local'.length)
    expect(update).not.toHaveBeenCalled()
  })

  it('목록 조회가 실패하면 실패라고 말한다 — 빈 목록으로 보이지 않는다', async () => {
    stubUser('ADMIN')
    vi.spyOn(session, 'listUsers').mockRejectedValue(new session.AuthRequestError('계정 목록을 불러오지 못했습니다.', 500))
    renderPanel()
    await waitFor(() => expect(screen.getByText('계정 목록을 불러오지 못했습니다.')).toBeTruthy())
    expect(screen.queryByTestId('acc-users')).toBeNull()
  })
})

/**
 * 비밀번호 변경 성공 안내가 **보인다** (`#1099`). `#825` ⑷가 성공 뒤 캐시를 비워 패널이 사용자
 * 없이 그려지지 않았고, 안내(무효화된 기기 수)는 한 번도 보이지 않았다.
 */
describe('비밀번호 변경 성공 안내 (#1099)', () => {
  it('안내와 「로그인 화면으로」가 보이고, 누르면 그때 세션을 해제한다', async () => {
    stubUser('FIELD')
    vi.spyOn(session, 'changePassword').mockResolvedValue(
      '비밀번호가 변경되었습니다. 로그인된 기기 2대에서 로그아웃되었습니다.',
    )
    const leave = vi.spyOn(session, 'leaveAfterPasswordChange').mockImplementation(() => {})
    renderPanel()
    fireEvent.change(screen.getByLabelText('현재 비밀번호'), { target: { value: 'old-password-1' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'new-password-12' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호 확인'), { target: { value: 'new-password-12' } })
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 바꾸기' }))
    expect(await screen.findByText(/로그인된 기기 2대에서 로그아웃되었습니다/)).toBeTruthy()
    const button = screen.getByRole('button', { name: '로그인 화면으로' })
    expect(leave).not.toHaveBeenCalled()
    fireEvent.click(button)
    expect(leave).toHaveBeenCalledTimes(1)
  })
})

/**
 * ⚠️ 목록에 있는 절이 **화면에 실재한다** (#2074 · #1791).
 *
 * ## 왜 이 검사가 필요한가
 *
 * `settingsSections.ts`는 목차와 절을 **한 목록에서** 만들어 「목차에 없는 절」과
 * 「없는 자리로 가는 링크」를 막는다. 그런데 그 장치는 **절로 만든 것**만 지킨다 —
 * 절로 만들지 않은 동작은 목록에 들어갈 기회 자체가 없어 **가드가 원리상 볼 수 없다.**
 *
 * `#2074`가 그 사각이었다: 표시 이름 변경이 「계정 정보」 절 안쪽에 제목 없는
 * 폼으로 들어 있어, 목차 다섯 줄 어디에도 없는데 **모든 검사가 초록**이었다.
 *
 * 그래서 방향을 뒤집어 잠근다 — **목록의 모든 `id`가 실제로 그려지는가.** 절을
 * 지우거나 `id`를 오타 내면 목차에 죽은 링크가 남는데, 그것도 여기서 붉어진다.
 */
describe('설정 목차의 모든 절이 화면에 있다 (#2074)', () => {
  function renderSettings(role: session.UserRole) {
    stubUser(role)
    return render(
      <MemoryRouter>
        <AccountPanel />
        <RegulationParametersSection />
      </MemoryRouter>,
    )
  }

  it.each(['ADMIN', 'OFFICE', 'FIELD'] as const)('%s — 목록의 id가 전부 실재한다', (role) => {
    renderSettings(role)
    const missing = visibleSections(role === 'ADMIN')
      .filter((section) => document.getElementById(section.id) === null)
      .map((section) => `${section.label}(#${section.id})`)
    expect(
      missing,
      '목차에 있는데 화면에 없는 절입니다 — 눌러도 아무 데도 가지 않습니다',
    ).toEqual([])
  })

  it('표시 이름이 「계정 정보」가 아니라 **자기 절** 안에 있다', () => {
    /*
     * 「계정 정보」는 바꿀 수 없는 사실(이메일 · 역할)만 진다. 폼이 그 절로 다시
     * 들어가면 목차에서 또 사라지는데, 위 검사는 `#profile`이 비어 있어도 통과한다.
     */
    renderSettings('FIELD')
    const input = screen.getByLabelText('표시 이름')
    expect(input.closest('#profile'), '표시 이름이 프로필 절 안에 없습니다').not.toBeNull()
    expect(input.closest('#account-info')).toBeNull()
  })

  it('목차 이름이 화면의 절 제목과 같다 — 둘이 갈리지 않는다', () => {
    /*
     * 이름을 대는 방법은 절마다 다르다 — 계정 쪽은 `aria-label`, 규제 기준값은
     * `aria-labelledby`로 제목을 가리킨다. **어느 방법인지**가 아니라 **무엇으로
     * 읽히는지**를 본다. 여기가 갈리면 목차에서 누른 이름과 도착한 절의 제목이
     * 달라, 사용자는 잘못 온 줄 안다.
     */
    renderSettings('FIELD')
    for (const section of visibleSections(false)) {
      const node = document.getElementById(section.id)
      expect(node, `${section.id} 절이 없습니다`).not.toBeNull()
      const labelledBy = node!.getAttribute('aria-labelledby')
      const name =
        node!.getAttribute('aria-label') ??
        (labelledBy === null ? null : document.getElementById(labelledBy)?.textContent?.trim())
      expect(name, `${section.id} 절이 이름을 대지 않습니다`).toBe(section.label)
    }
  })
})

describe('프로필 이미지 — #2080', () => {
  it('고르기 전에는 「올리기」가 잠겨 있다 — 올릴 것이 없다', () => {
    /*
     * 잠근 사유는 곁의 「선택된 파일 없음」이 **글자로** 말한다(`PRD §6.4` 파일 선택
     * 행 · `§14`). 그래서 따로 사유를 잇지 않는다 — `a11yWiring`에 그렇게 등재돼 있다.
     */
    stubUser()
    renderPanel()
    expect((screen.getByRole('button', { name: '올리기' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('고르면 풀리고, 올리면 그 파일이 서버로 간다', async () => {
    stubUser()
    const upload = vi.spyOn(session, 'uploadAvatar').mockResolvedValue({
      id: 'u-1',
      email: 'demo@bluelog.local',
      displayName: '테스터',
      role: 'FIELD',
      emailVerifiedAt: null,
      hasAvatar: true,
    })
    renderPanel()

    const file = new File([new Uint8Array([1, 2, 3])], 'me.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('프로필 이미지 파일'), { target: { files: [file] } })

    const button = screen.getByRole('button', { name: '올리기' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    fireEvent.click(button)

    await waitFor(() => expect(upload).toHaveBeenCalledWith(file))
    await waitFor(() =>
      expect(screen.getByRole('status').textContent).toContain('프로필 이미지를 올렸습니다'),
    )
  })

  it('2MB를 넘는 파일은 **고른 자리에서** 막는다 — 서버로 보내지 않는다 (#2107)', () => {
    /*
     * 종전에는 고른 파일을 보지 않고 그대로 올려, 큰 사진도 끝까지 보낸 뒤에야
     * 「너무 큽니다」를 받았다. 버튼만 잠그면 왜 잠겼는지 알 수 없으므로 사유도 함께 낸다.
     */
    stubUser()
    const upload = vi.spyOn(session, 'uploadAvatar')
    renderPanel()

    const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('프로필 이미지 파일'), { target: { files: [big] } })

    const button = screen.getByRole('button', { name: '올리기' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByRole('alert').textContent).toContain('2MB')
    fireEvent.click(button)
    expect(upload).not.toHaveBeenCalled()

    // 올릴 수 있는 파일로 다시 고르면 사유가 걷히고 버튼이 풀린다.
    const ok = new File([new Uint8Array([1, 2, 3])], 'me.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('프로필 이미지 파일'), { target: { files: [ok] } })
    expect(button.disabled).toBe(false)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('받지 않는 형식도 고른 자리에서 막는다 (#2107)', () => {
    stubUser()
    renderPanel()
    const svg = new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })
    fireEvent.change(screen.getByLabelText('프로필 이미지 파일'), { target: { files: [svg] } })

    expect((screen.getByRole('button', { name: '올리기' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('alert').textContent).toContain('PNG')
  })

  it('「지우기」는 **올린 뒤에만** 보인다', () => {
    /*
     * 없는 것을 지우는 단추는 무엇을 하는지 알 수 없다. 서버는 멱등이라 눌러도
     * 성공하지만, 그 성공이 화면에서는 아무 변화가 아니다.
     */
    stubUser('FIELD', false)
    const { unmount } = renderPanel()
    expect(screen.queryByRole('button', { name: '지우기' })).toBeNull()
    unmount()

    stubUser('FIELD', true)
    renderPanel()
    expect(screen.getByRole('button', { name: '지우기' })).toBeTruthy()
  })

  it('받는 형식이 서버와 같고 **SVG가 없다**', () => {
    /*
     * `accept`는 거름망이 아니라 **안내**다(사용자가 「모든 파일」로 바꿀 수 있다).
     * 그래도 여기 SVG가 있으면 고를 수 있는 것처럼 보였다가 서버가 422로 막는다.
     */
    stubUser()
    renderPanel()
    const accept = screen.getByLabelText('프로필 이미지 파일').getAttribute('accept') ?? ''
    expect(accept.split(',')).toEqual(['image/png', 'image/jpeg', 'image/webp'])
    expect(accept).not.toContain('svg')
  })

  it('안내가 **형식과 크기를 함께** 말한다', () => {
    /*
     * 크기만 적으면 형식이 틀렸을 때 사용자가 크기를 줄여 보다가 또 막힌다.
     * 서버가 다시 그린다는 사실도 적는다 — 설명이 없으면 결함으로 읽힌다.
     */
    stubUser()
    renderPanel()
    const notice = screen.getByText(/PNG/)
    expect(notice.textContent).toContain('2MB')
    expect(notice.textContent).toContain('정사각형')
  })
})
