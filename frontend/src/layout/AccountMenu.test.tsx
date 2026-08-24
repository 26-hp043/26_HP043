// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AccountMenu } from './AccountMenu'
import { SCREEN_BY_ID } from '../screens'
import type { CurrentUser } from '../auth/session'

/**
 * 상단바 계정 팝오버 (#717).
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
  emailVerifiedAt: null,
}

function renderMenu(user: CurrentUser = USER, path = '/dashboard') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AccountMenu user={user} />
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
