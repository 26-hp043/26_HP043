// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RequireOffice } from './RequireOffice'
import { OFFICE_ONLY_SCREEN_NOTICE } from '../features/auth/authRules'
import * as session from './session'

/**
 * 사무직 전용 화면 가드 (`#672`).
 *
 * 현장직은 **로그인으로 튕기지 않고** 자리에서 이유를 읽는다 — 다시 로그인해도 같기
 * 때문이다. 사무직은 그대로 지나간다. 비인증(`null`)은 현장직과 같은 답이다 — 모르면
 * 좁은 쪽으로.
 */
function stub(user: session.CurrentUser | null) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue(user)
}

const OFFICE: session.CurrentUser = {
  id: 'u1',
  email: 'office@b.c',
  displayName: null,
  role: 'OFFICE',
  emailVerifiedAt: null,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RequireOffice (#672)', () => {
  it('사무직은 자식을 그대로 그린다', () => {
    stub(OFFICE)
    render(
      <RequireOffice>
        <p>보고서 화면</p>
      </RequireOffice>,
    )
    expect(screen.getByText('보고서 화면')).toBeTruthy()
    expect(screen.queryByText(OFFICE_ONLY_SCREEN_NOTICE)).toBeNull()
  })

  it('현장직은 자식 대신 안내를 본다 — 이동하지 않는다', () => {
    stub({ ...OFFICE, role: 'FIELD' })
    render(
      <RequireOffice>
        <p>보고서 화면</p>
      </RequireOffice>,
    )
    expect(screen.queryByText('보고서 화면')).toBeNull()
    expect(screen.getByText(OFFICE_ONLY_SCREEN_NOTICE)).toBeTruthy()
  })

  it('사용자를 모르면 현장직과 같다 — 넓게 틀리지 않는다', () => {
    stub(null)
    render(
      <RequireOffice>
        <p>보고서 화면</p>
      </RequireOffice>,
    )
    expect(screen.queryByText('보고서 화면')).toBeNull()
  })
})
