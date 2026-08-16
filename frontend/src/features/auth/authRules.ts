/**
 * 인증 화면의 입력 검증 (#415).
 *
 * ## 서버 규칙을 그대로 옮긴다
 *
 * 최소 길이는 `auth/password.py`의 `MIN_PASSWORD_LENGTH`와 **같은 값**이다. 화면이
 * 더 느슨하면 제출 후 거부되어 사용자가 다시 입력해야 하고, 더 엄격하면 서버가
 * 허용하는 비밀번호를 화면이 막는다.
 *
 * ## 화면 검증은 편의이지 방어가 아니다
 *
 * 서버가 같은 검사를 다시 한다. 여기서 거르는 목적은 **왕복 한 번을 아끼는 것**이며,
 * 여기를 통과했다고 서버가 통과시킨다는 뜻은 아니다.
 */

/** 서버 `MIN_PASSWORD_LENGTH`와 같은 값. */
export const MIN_PASSWORD_LENGTH = 10
/** 서버 `MAX_PASSWORD_LENGTH`와 같은 값. */
export const MAX_PASSWORD_LENGTH = 128

/** 서버 `EMAIL_PATTERN`·DB `chk_app_user_email_format`과 같은 규칙. */
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+$/

export interface FieldErrors {
  email?: string
  password?: string
  passwordConfirm?: string
}

export function validateEmail(email: string): string | undefined {
  const trimmed = email.trim()
  if (!trimmed) return '이메일을 입력해 주세요.'
  if (!EMAIL_PATTERN.test(trimmed)) return '이메일 형식이 올바르지 않습니다.'
  return undefined
}

export function validatePassword(password: string): string | undefined {
  if (!password) return '비밀번호를 입력해 주세요.'
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `비밀번호는 ${MAX_PASSWORD_LENGTH}자를 넘을 수 없습니다.`
  }
  return undefined
}

/** 로그인 — 비밀번호는 **빈 값만** 본다. 길이 규칙을 여기서 적용하면 안 된다. */
export function validateLogin(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {}
  const emailError = validateEmail(email)
  if (emailError) errors.email = emailError
  /*
   * 기존 사용자의 비밀번호가 지금 정책보다 짧을 수 있다. 로그인 화면에서 길이를
   * 검사하면 **그 사용자는 로그인 자체를 시도할 수 없다.** 판정은 서버가 한다.
   */
  if (!password) errors.password = '비밀번호를 입력해 주세요.'
  return errors
}

export function validateSignup(
  email: string,
  password: string,
  passwordConfirm: string,
): FieldErrors {
  const errors: FieldErrors = {}
  const emailError = validateEmail(email)
  if (emailError) errors.email = emailError
  const passwordError = validatePassword(password)
  if (passwordError) errors.password = passwordError
  if (password !== passwordConfirm) {
    errors.passwordConfirm = '비밀번호가 일치하지 않습니다.'
  }
  return errors
}

export function hasErrors(errors: FieldErrors): boolean {
  return Object.values(errors).some(Boolean)
}

/**
 * `?next=` 복귀 경로 — **앱 내부 경로만** 허용한다.
 *
 * 외부 URL을 그대로 쓰면 open redirect가 된다. 로그인 직후 이동하는 자리라
 * 공격자가 이 값을 심으면 사용자가 로그인한 상태로 외부 사이트에 도착한다.
 */
export function safeNext(raw: string | null): string {
  if (!raw) return '/'
  return raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
}

/** 이메일 인증 여부. `null`이면 미인증이며 배너를 띄운다. */
export function isEmailVerified(emailVerifiedAt: string | null): boolean {
  return emailVerifiedAt !== null
}
