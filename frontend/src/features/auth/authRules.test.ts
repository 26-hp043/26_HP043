import { describe, expect, it } from 'vitest'
import {
  EMAIL_IMMUTABLE_NOTICE,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  hasErrors,
  isEmailVerified,
  safeNext,
  splitSubmitFailure,
  validateEmail,
  validateLogin,
  validatePassword,
  validateSignup,
} from './authRules'
import { AuthRequestError } from '../../auth/session'

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

describe('이메일 변경 불가 고지 (#506)', () => {
  it('PRD §6.3이 확정한 문구를 그대로 쓴다', () => {
    /*
     * 표시 문구가 아니라 **정본이 확정한 문구**다(`AGENTS §4.6` · `#468`이 정한
     * 구분). 화면에서 임의로 바꾸면 정본과 갈린다.
     */
    expect(EMAIL_IMMUTABLE_NOTICE).toBe(
      '가입 후에는 이메일을 변경할 수 없습니다. 다른 주소를 쓰려면 탈퇴 후 다시 가입해 주세요.',
    )
  })

  it('탈퇴 후 재가입이라는 대안을 함께 말한다', () => {
    // 「바꿀 수 없다」만 적으면 사용자는 막다른 길로 읽는다. 서버는 탈퇴한 계정의
    // 이메일을 다시 쓸 수 있게 두었으므로(부분 유일 인덱스) 그 길을 안내한다.
    expect(EMAIL_IMMUTABLE_NOTICE).toContain('탈퇴')
    expect(EMAIL_IMMUTABLE_NOTICE).toContain('다시 가입')
  })
})

/**
 * 제출 실패를 칸과 폼 위로 나눈다 (#877 ⑴).
 *
 * 서버가 짚은 필드가 이 폼에 있으면 **그 칸에만**, 없으면 **폼 위**에. 선박 등록의
 * `toFormErrors`와 같은 규율이다.
 */
describe('splitSubmitFailure (#877)', () => {
  const FIELDS = { email: 'email', display_name: 'displayName' } as const

  it('이 폼의 칸이면 그 칸에만 붙이고 폼 위는 비운다', () => {
    const error = new AuthRequestError('표시 이름은 100자 이하여야 합니다.', 422, {
      display_name: '표시 이름은 100자 이하여야 합니다.',
    })
    expect(splitSubmitFailure(error, '기본', FIELDS)).toEqual({
      errors: { displayName: '표시 이름은 100자 이하여야 합니다.' },
      failure: null,
    })
  })

  it('칸이 없는 필드의 문구는 폼 위로 — 버리지 않는다', () => {
    const error = new AuthRequestError('링크가 만료되었습니다.', 422, {
      token: '링크가 만료되었습니다.',
      email: '이메일 형식이 올바르지 않습니다.',
    })
    expect(splitSubmitFailure(error, '기본', FIELDS)).toEqual({
      errors: { email: '이메일 형식이 올바르지 않습니다.' },
      failure: '링크가 만료되었습니다.',
    })
  })

  it('필드가 없는 실패는 서버 문구를 폼 위에', () => {
    const error = new AuthRequestError('가입이 허용되지 않았습니다.', 422)
    expect(splitSubmitFailure(error, '기본', FIELDS)).toEqual({
      errors: {},
      failure: '가입이 허용되지 않았습니다.',
    })
  })

  it('인증 요청 오류가 아니면 화면의 기본 문구를 쓴다', () => {
    expect(splitSubmitFailure(new TypeError('x'), '기본 문구', FIELDS)).toEqual({
      errors: {},
      failure: '기본 문구',
    })
  })

  it('프로토타입 속성 이름을 필드로 오인하지 않는다', () => {
    const error = new AuthRequestError('m', 422, { toString: '이상한 필드' })
    expect(splitSubmitFailure(error, '기본', FIELDS).failure).toBe('이상한 필드')
  })
})
