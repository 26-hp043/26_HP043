// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { SignupPage } from './SignupPage'
import { probeCurrentUser } from '../auth/session'

/**
 * 회원가입 화면의 면책 문구 (`#1455`).
 *
 * `UIFLOW §0` `0-1`이 회원가입의 구성 요소로 「면책 문구」를 적는데, 화면은 로그인에만
 * 켜 두고 있었다. `AuthShell` 단위 검사는 **깃발이 켜지면 나온다**는 것만 보므로,
 * 이 화면이 깃발을 **켜는지**는 여기서 본다.
 */

afterEach(async () => {
  // 사용자 캐시는 모듈 전역이다 — 로그인 상태가 남으면 화면이 `<Navigate>`로 빠진다.
  await probeCurrentUser(async () => ({ ok: false, status: 401, json: async () => null }) as Response)
})

function renderSignup() {
  return render(
    <MemoryRouter initialEntries={['/signup']}>
      <SignupPage />
    </MemoryRouter>,
  )
}

describe('회원가입 면책 문구 (#1455)', () => {
  it('카드 안, 가입 버튼 뒤에 면책 문구가 있다', () => {
    const { container } = renderSignup()

    const card = container.querySelector('.auth-card')
    const note = container.querySelector('.auth-disclaimer')
    const submit = container.querySelector('button[type="submit"]')
    expect(note).not.toBeNull()
    expect(submit).not.toBeNull()
    expect(card?.contains(note)).toBe(true)
    // 로그인과 같은 자리(#1425) — 첫 시선이 고지가 아니라 입력에 간다.
    expect(submit!.compareDocumentPosition(note!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('서비스 소개는 켜지 않는다 — 0-1은 면책만 적는다', () => {
    const { container } = renderSignup()
    expect(container.querySelector('.auth-intro')).toBeNull()
  })
})
