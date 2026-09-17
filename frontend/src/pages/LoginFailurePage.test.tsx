// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { LoginFailurePage } from './LoginPage'
import { PAGE_FAILURE_TITLE, actionFailureTitle } from '../components/errorCopy'

/**
 * 로그인 실패 화면의 **층위** (`#1053` · 2026-09-17 확정).
 *
 * 2026-09-11 확정 C ⑶은 이 화면을 A층위(페이지 실패) 이관 대상으로 두었는데,
 * A층위 제목은 **고정** 「화면을 불러오지 못했습니다」다(확정 B). 이 화면은 화면이
 * 안 뜬 것이 아니라 **로그인이 실패한 것**이라 그 제목이 뜻과 어긋난다.
 *
 * 영역 실패의 「처리」 갈래로 두고, 제목은 `actionFailureTitle`이 만든다 —
 * **A층위에 예외를 만들지 않는 것**이 확정의 핵심이라 그 둘을 함께 잠근다.
 */
describe('로그인 실패 화면의 층위 (#1053)', () => {
  it('제목이 「로그인에 실패했습니다」다 — 호출부가 지은 문자열이 아니다', () => {
    render(
      <MemoryRouter>
        <LoginFailurePage />
      </MemoryRouter>,
    )
    expect(screen.getByText(actionFailureTitle('로그인'))).not.toBeNull()
  })

  it('페이지 실패 고정 제목을 쓰지 않는다', () => {
    /* 여기가 실패하면 A층위로 되돌아간 것이다 — 「화면이 안 떴다」로 읽힌다. */
    render(
      <MemoryRouter>
        <LoginFailurePage />
      </MemoryRouter>,
    )
    expect(screen.queryByText(PAGE_FAILURE_TITLE)).toBeNull()
  })

  it('재시도 문구가 단일 문구 「다시 시도」다', () => {
    /* `ErrorState`가 준다 — 종전에는 호출부가 링크에 직접 적었다. */
    render(
      <MemoryRouter>
        <LoginFailurePage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: '다시 시도' })).not.toBeNull()
  })
})
