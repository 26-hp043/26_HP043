import { describe, expect, it } from 'vitest'
import {
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  hasErrors,
  isEmailVerified,
  safeNext,
  validateEmail,
  validateLogin,
  validatePassword,
  validateSignup,
} from './authRules'

/**
 * 인증 화면 입력 규칙 (#415).
 *
 * 여기서 고정하는 것은 **화면이 서버보다 엄격해지지 않는 것**이다. 화면이 더 엄격하면
 * 서버가 허용하는 입력을 막고, 특히 로그인에서는 **기존 사용자가 로그인 자체를
 * 시도할 수 없게 된다.**
 */

const VALID = 'correct-horse-battery'

describe('이메일', () => {
  it('형식이 맞으면 통과', () => {
    expect(validateEmail('user@example.com')).toBeUndefined()
  })

  it('빈 값', () => {
    expect(validateEmail('   ')).toContain('입력')
  })

  it.each(['not-an-email', 'a@', '@b', 'a b@c.com'])('%s는 거부', (raw) => {
    expect(validateEmail(raw)).toBeDefined()
  })
})

describe('비밀번호 정책 — 서버와 같은 값', () => {
  it('최소 길이가 서버 상수와 같다', () => {
    // 서버 auth/password.py의 MIN_PASSWORD_LENGTH와 같아야 한다.
    expect(MIN_PASSWORD_LENGTH).toBe(10)
    expect(MAX_PASSWORD_LENGTH).toBe(128)
  })

  it('정확히 최소 길이는 통과', () => {
    expect(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH))).toBeUndefined()
  })

  it('한 자 모자라면 거부', () => {
    expect(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH - 1))).toContain('10자')
  })

  it('최대 길이 초과는 거부', () => {
    expect(validatePassword('a'.repeat(MAX_PASSWORD_LENGTH + 1))).toContain('128자')
  })

  it('복잡도를 요구하지 않는다', () => {
    // 서버와 같은 판단 — 길이를 우선한다(NIST SP 800-63B).
    expect(validatePassword('aaaaaaaaaaaaaaaa')).toBeUndefined()
  })
})

describe('로그인 검증', () => {
  it('올바른 입력은 오류가 없다', () => {
    expect(hasErrors(validateLogin('a@b.com', VALID))).toBe(false)
  })

  it('**짧은 비밀번호를 막지 않는다**', () => {
    /*
     * 기존 사용자의 비밀번호가 지금 정책보다 짧을 수 있다. 로그인 화면에서 길이를
     * 검사하면 그 사용자는 로그인 자체를 시도할 수 없다. 판정은 서버가 한다.
     */
    expect(validateLogin('a@b.com', 'short').password).toBeUndefined()
  })

  it('빈 비밀번호는 막는다 — 왕복 한 번을 아낀다', () => {
    expect(validateLogin('a@b.com', '').password).toBeDefined()
  })
})

describe('회원가입 검증', () => {
  it('올바른 입력은 오류가 없다', () => {
    expect(hasErrors(validateSignup('a@b.com', VALID, VALID))).toBe(false)
  })

  it('비밀번호 확인 불일치', () => {
    expect(validateSignup('a@b.com', VALID, 'different-one').passwordConfirm).toBeDefined()
  })

  it('가입에서는 길이 정책을 적용한다', () => {
    expect(validateSignup('a@b.com', 'short', 'short').password).toBeDefined()
  })
})

describe('safeNext — open redirect 방어', () => {
  it('내부 경로는 그대로', () => {
    expect(safeNext('/dashboard')).toBe('/dashboard')
  })

  it('쿼리스트링 보존', () => {
    expect(safeNext('/annual-grade?vessel=1')).toBe('/annual-grade?vessel=1')
  })

  it.each([
    ['null', null],
    ['절대 URL', 'https://evil.example.com'],
    ['프로토콜 상대 URL', '//evil.example.com'],
    ['상대 경로', 'dashboard'],
  ])('%s는 루트로 대체', (_label, raw) => {
    expect(safeNext(raw)).toBe('/')
  })
})

describe('이메일 인증 상태', () => {
  it('시각이 있으면 인증됨', () => {
    expect(isEmailVerified('2026-08-17T00:00:00Z')).toBe(true)
  })

  it('null이면 미인증 — 배너를 띄운다', () => {
    expect(isEmailVerified(null)).toBe(false)
  })
})
