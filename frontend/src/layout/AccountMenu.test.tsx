// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AccountMenu } from './AccountMenu'
import { SCREEN_BY_ID } from '../screens'
import type { CurrentUser } from '../auth/session'
import { ROLE_LABEL } from '../features/auth/authRules'
import { ko } from '../i18n/ko'

/**
 * 계정 팝오버 (#717) — #2203부터 사이드바 로고 아래 사용자 카드다.
 *
 * ## 무엇을 잠그나
 *
 * 여닫힘은 **눈으로만 확인하기 쉬운 자리**다. 열리는 것은 바로 보이지만 **닫히는
 * 경로 세 가지**(Esc · 바깥 클릭 · 경로 이동)는 하나가 빠져도 화면이 깨지지 않아
 * 조용히 남는다. 실제로 이 패널은 「설정」을 누른 뒤 남으면 **막 도착한 화면을
 * 자기가 가린다.**
 *
 * 접근성 계약(`aria-expanded` ↔ `hidden`)도 함께 본다. 둘이 갈리면 스크린 리더가
 * 「펼쳐짐」이라 읽는데 화면에는 아무것도 없다.
 */

const USER: CurrentUser = {
  id: 'u1',
  email: 'demo@bluelog.local',
  displayName: '시연용',
  role: 'OFFICE',
  emailVerifiedAt: null,
  hasAvatar: false,
}

function renderMenu(
  user: CurrentUser = USER,
  path = '/dashboard',
  { onLogout = () => {}, logoutFailure = null }: { onLogout?: () => void; logoutFailure?: string | null } = {},
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AccountMenu user={user} onLogout={onLogout} logoutFailure={logoutFailure} />
    </MemoryRouter>,
  )
}

const trigger = () => screen.getByTestId('account-trigger')
const panel = () => screen.getByTestId('account-panel')

describe('계정 팝오버 — 여닫힘 (#717)', () => {
  it('처음에는 닫혀 있고 두 표시가 일치한다', () => {
    renderMenu()
    expect(trigger().getAttribute('aria-expanded')).toBe('false')
    expect(panel().hasAttribute('hidden')).toBe(true)
  })

  it('누르면 열리고 계정 요약과 설정 진입이 함께 나온다', () => {
    renderMenu()
    fireEvent.click(trigger())

    expect(trigger().getAttribute('aria-expanded')).toBe('true')
    expect(panel().hasAttribute('hidden')).toBe(false)
    expect(screen.getByText(USER.email)).toBeDefined()
    expect(screen.getByRole('link', { name: /설정/ }).getAttribute('href')).toBe(
      SCREEN_BY_ID.SETTINGS.path,
    )
  })

  it('Esc로 닫힌다', () => {
    renderMenu()
    fireEvent.click(trigger())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(panel().hasAttribute('hidden')).toBe(true)
  })

  it('바깥을 누르면 닫힌다', () => {
    renderMenu()
    fireEvent.click(trigger())
    fireEvent.mouseDown(document.body)
    expect(panel().hasAttribute('hidden')).toBe(true)
  })

  it('패널 안을 눌러도 닫히지 않는다 — 링크가 눌리기 전에 사라지면 안 된다', () => {
    renderMenu()
    fireEvent.click(trigger())
    fireEvent.mouseDown(panel())
    expect(panel().hasAttribute('hidden')).toBe(false)
  })

  /*
   * `aria-controls`가 가리키는 id가 **닫혔을 때도 존재**해야 한다. 패널을 조건부로
   * 렌더하면 그 참조가 끊긴 id를 가리킨다 — 화면은 멀쩡해 보인다.
   */
  it('aria-controls가 실제 요소를 가리킨다 — 닫혀 있을 때도', () => {
    renderMenu()
    const id = trigger().getAttribute('aria-controls')
    expect(id).toBeTruthy()
    // `useId()`가 만드는 id에는 콜론이 들어간다 — 선택자로 쓰면 이스케이프가 필요해
    // `getElementById`로 찾는다.
    expect(document.getElementById(id as string)).toBe(panel())
  })
})

/**
 * 테마·언어가 **패널 안에서 실제로 동작한다** (`#1422`).
 *
 * 옮기는 작업은 「보이는가」만 확인하고 끝내기 쉬운데, 이 둘은 **보이면서 죽어
 * 있을 수 있다** — 패널이 `hidden`으로 감춰지는 구조라 열지 않은 채로도 DOM에
 * 남아 있고, 라벨 배선(`aria-labelledby`)은 눈으로 보이지 않는다.
 */
describe('계정 팝오버 — 테마·언어 (#1422)', () => {
  it('패널 안에 두 선택이 있고 보이는 라벨이 그룹 이름을 맡는다', () => {
    renderMenu()
    fireEvent.click(trigger())

    for (const name of [/화면 테마/, /언어/]) {
      const group = screen.getByRole('radiogroup', { name })
      // 패널 **안**에 있다 — 상단바에 남아 있으면 §7.2를 다시 벗어난다.
      expect(group.closest('[data-testid="account-panel"]')).not.toBeNull()
      /*
       * 이름을 `aria-label`이 아니라 **보이는 글자**가 준다. 둘 다 들고 있으면 같은
       * 말이 두 벌이 되고, 한쪽만 고치는 날 화면과 낭독이 갈린다.
       */
      expect(group.getAttribute('aria-labelledby')).toBeTruthy()
      expect(group.getAttribute('aria-label')).toBeNull()
    }
  })

  it('패널 안에서 테마를 실제로 바꾼다 — 보이기만 하는 것이 아니다', () => {
    renderMenu()
    fireEvent.click(trigger())

    const dark = screen.getByTestId('theme-dark')
    expect(dark.getAttribute('aria-checked')).toBe('false')

    fireEvent.click(dark)

    expect(dark.getAttribute('aria-checked')).toBe('true')
    expect(screen.getByTestId('theme-light').getAttribute('aria-checked')).toBe('false')
    // 패널은 열린 채로 남는다 — 바꾼 결과를 그 자리에서 봐야 한다.
    expect(panel().hasAttribute('hidden')).toBe(false)
  })
})

describe('계정 팝오버 — 인증 상태 (#717)', () => {
  it('미인증이면 대기로 읽힌다', () => {
    renderMenu()
    fireEvent.click(trigger())
    expect(screen.getByText('이메일 인증 대기')).toBeDefined()
  })

  it('인증됐으면 완료로 읽힌다', () => {
    renderMenu({ ...USER, emailVerifiedAt: '2026-08-24T00:00:00Z' })
    fireEvent.click(trigger())
    expect(screen.getByText('이메일 인증 완료')).toBeDefined()
  })

  it('표시 이름이 없으면 이메일을 트리거에 쓰고 패널에서 비어 있음을 밝힌다', () => {
    renderMenu({ ...USER, displayName: null })
    expect(trigger().textContent).toContain(USER.email)
    fireEvent.click(trigger())
    expect(screen.getByText('표시 이름 없음')).toBeDefined()
  })
})

describe('사이드바 사용자 카드 — 역할 · 둘러보기 · 로그아웃 (#2203)', () => {
  it('카드에 이름과 역할이 함께 보이고, 둘 다 버튼 이름에 든다', () => {
    renderMenu()
    expect(trigger().textContent).toContain('시연용')
    expect(trigger().textContent).toContain('사무직')
  })

  it.each([
    ['FIELD', '현장직'],
    ['OFFICE', '사무직'],
    ['ADMIN', '관리자'],
  ] as const)('역할 %s는 「%s」다', (role, text) => {
    renderMenu({ ...USER, role })
    expect(trigger().textContent).toContain(text)
  })

  it('둘러보기 계정은 ADMIN이어도 「관리자」가 아니라 「둘러보기」다', () => {
    renderMenu({ ...USER, role: 'ADMIN', isTour: true })
    expect(trigger().textContent).toContain('둘러보기')
    expect(trigger().textContent).not.toContain('관리자')
  })

  it('역할 글자는 `ROLE_LABEL`과 같다 — 계정 관리 화면과 갈리지 않는다', () => {
    expect(ko['account.role.OFFICE']).toBe(ROLE_LABEL.OFFICE)
    expect(ko['account.role.FIELD']).toBe(ROLE_LABEL.FIELD)
    expect(ko['account.role.ADMIN']).toBe(ROLE_LABEL.ADMIN)
  })

  it('로그아웃은 패널 안에 있고, 누르면 셸에 알린다', () => {
    const onLogout = vi.fn()
    renderMenu(USER, '/dashboard', { onLogout })
    const panel = screen.getByTestId('account-panel')
    const button = screen.getByTestId('logout-button')
    expect(panel.contains(button)).toBe(true)
    fireEvent.click(trigger())
    fireEvent.click(button)
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('로그아웃이 서버에서 실패하면 버튼 아래에 알린다 — 버튼은 남는다 (#825 ⑵)', () => {
    renderMenu(USER, '/dashboard', { logoutFailure: '로그아웃하지 못했습니다.' })
    fireEvent.click(trigger())
    expect(screen.getByRole('alert').textContent).toBe('로그아웃하지 못했습니다.')
    expect(screen.getByTestId('logout-button')).toBeDefined()
  })
})
