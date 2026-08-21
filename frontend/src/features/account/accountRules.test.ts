import { describe, expect, it } from 'vitest'
import { hasErrors } from '../auth/authRules'
import {
  MAX_DISPLAY_NAME_LENGTH,
  displayNamePayload,
  validateDisplayName,
  validatePasswordChange,
} from './accountRules'
import type { PasswordChangeDraft } from './accountRules'

const draft = (over: Partial<PasswordChangeDraft> = {}): PasswordChangeDraft => ({
  currentPassword: 'old-password-1',
  newPassword: 'new-password-1',
  confirmPassword: 'new-password-1',
  ...over,
})

describe('validateDisplayName', () => {
  it('빈 이름을 허용한다 — display_name은 nullable이고 지우는 것도 조작이다', () => {
    expect(validateDisplayName('')).toBeUndefined()
  })

  it('서버 길이 제약과 같은 값에서 막는다', () => {
    expect(validateDisplayName('가'.repeat(MAX_DISPLAY_NAME_LENGTH))).toBeUndefined()
    expect(validateDisplayName('가'.repeat(MAX_DISPLAY_NAME_LENGTH + 1))).toBeDefined()
  })
})

describe('displayNamePayload', () => {
  it('빈 이름은 null로 보낸다 — 빈 문자열은 서버가 무엇으로 읽을지 모호하다', () => {
    expect(displayNamePayload('   ')).toEqual({ display_name: null })
  })

  it('앞뒤 공백을 다듬는다', () => {
    expect(displayNamePayload('  김수민 ')).toEqual({ display_name: '김수민' })
  })

  it('email을 절대 싣지 않는다 — PATCH /auth/me는 extra="forbid"다', () => {
    expect(Object.keys(displayNamePayload('김수민'))).toEqual(['display_name'])
  })
})

describe('validatePasswordChange', () => {
  it('정상 입력은 통과한다', () => {
    expect(hasErrors(validatePasswordChange(draft()))).toBe(false)
  })

  it('현재 비밀번호는 비울 수 없다 — 맞는지는 서버만 안다', () => {
    expect(validatePasswordChange(draft({ currentPassword: '' })).currentPassword).toBeDefined()
  })

  it('새 비밀번호 확인이 다르면 잡는다', () => {
    expect(
      validatePasswordChange(draft({ confirmPassword: 'different-1' })).confirmPassword,
    ).toBeDefined()
  })

  it('짧은 새 비밀번호를 잡는다 — 가입 화면과 같은 규칙을 쓴다', () => {
    expect(validatePasswordChange(draft({ newPassword: 'short', confirmPassword: 'short' })).newPassword).toBeDefined()
  })

  /*
   * 서버가 받아 주더라도 **세션만 전량 무효화되고 바뀐 것은 없는** 상태가 된다.
   * 사용자는 로그아웃만 당하고 얻는 것이 없다.
   */
  it('현재와 같은 비밀번호를 막는다', () => {
    const same = draft({ newPassword: 'old-password-1', confirmPassword: 'old-password-1' })
    expect(validatePasswordChange(same).newPassword).toBeDefined()
  })
})
