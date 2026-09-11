import { AuthRequestError } from '../../auth/session'

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
/**
 * 회원가입 — 이메일 변경 불가 고지 (#506).
 *
 * **`PRD §6.3` 표의 문구를 그대로 옮겼다.** 표시 문구가 아니라 **정본이 확정한
 * 문구**이므로 화면에서 임의로 고치지 않는다(`AGENTS §4.6` · `#468`이 정한 구분).
 *
 * 왜 가입 시점에 알리는가 — 이메일은 로그인 ID이자 `idx_app_user_email`의 키다.
 * 가입한 뒤에는 바꿀 수 없고, **바꾸려면 탈퇴 후 재가입해야 한다.** 그 사실을
 * 나중에 알면 이미 늦다.
 */
export const EMAIL_IMMUTABLE_NOTICE =
  '가입 후에는 이메일을 변경할 수 없습니다. 다른 주소를 쓰려면 탈퇴 후 다시 가입해 주세요.'

/**
 * 회원가입 — 초대 코드 안내 (#808). **`PRD §6.3` 표의 원문**이다.
 *
 * 사내 도구라 가입은 회사 메일 도메인 또는 초대 코드가 있어야 된다(`API_SPEC §1.2`).
 * 칸은 선택 입력이고, 이 안내가 「회사 메일이면 비워 둔다」를 대신 말한다.
 */
export const INVITE_CODE_HINT = '회사 이메일이 아니면 관리자에게 받은 초대 코드를 입력해 주세요.'

/**
 * 탈퇴 확인 문구 — **`PRD §6.3` 표의 원문을 그대로 옮겼다** (`#754`).
 *
 * 표시 문구가 아니라 **정본이 확정한 문구**이므로 화면에서 임의로 고치지 않는다
 * (`AGENTS §4.6` · `#468`이 정한 구분). 바로 위 `EMAIL_IMMUTABLE_NOTICE`와 같은
 * 성질이다.
 *
 * 세 가지를 한 문장에 담고 있고, 셋 다 **탈퇴 전에 알아야 하는 사실**이다.
 *
 * * 로그인할 수 없다 — 되돌릴 수 없는 조작임을 먼저 말한다
 * * 계산·감사 기록은 남는다 — soft delete라 행을 지우지 않는다. 규제 대응의 근거다
 *   (`DB_SCHEMA §7.1`·`§7.3`)
 * * 같은 이메일로 다시 가입할 수 있다 — `idx_app_user_email`이 `WHERE is_deleted =
 *   false`인 부분 유일 인덱스라 성립한다(마이그레이션 033). **이메일을 바꿀 유일한
 *   경로**이므로 이 문장이 특히 중요하다
 *
 * 종전에는 이 문구를 쓰는 코드가 저장소에 **한 곳도 없었다** — 정본이 원문을
 * 확정했는데 소비처가 0이었고, 화면 자체가 없었다(`#754`).
 */
export const WITHDRAWAL_NOTICE =
  '탈퇴하면 로그인할 수 없습니다. 계산·감사 기록은 규제 대응을 위해 보존되며, 같은 이메일로 다시 가입할 수 있습니다.'

export const MIN_PASSWORD_LENGTH = 10
/** 서버 `MAX_PASSWORD_LENGTH`와 같은 값. */
export const MAX_PASSWORD_LENGTH = 128

/** 서버 `EMAIL_PATTERN`·DB `chk_app_user_email_format`과 같은 규칙. */
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+$/

export interface FieldErrors {
  email?: string
  password?: string
  passwordConfirm?: string
  displayName?: string
  inviteCode?: string
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
 * 제출 실패를 화면 상태로 옮긴다 (#877 ⑴).
 *
 * 서버가 `error.details[]`로 **짚은 필드는 그 입력칸에** 붙이고, 이 폼에 칸이 없는 필드나
 * 필드 없는 실패(로그인 실패 · 가입 게이트 · 만료된 링크)는 **폼 위 문구**로 보인다.
 * 선박 등록(`vessel-registration/formRules.ts` `toFormErrors`)과 같은 규율이다.
 *
 * 문구는 **서버가 준 그대로** 쓴다 — 화면이 다시 쓰면 「계정 존재 여부를 숨긴다」는
 * 규칙(`PRD §6.3`)과 갈라질 수 있고, 한국어화는 서버가 한다(`API_SPEC §1.3.2` · `#900`).
 *
 * @param fields 서버 필드 경로(`display_name`) → 이 폼의 키(`displayName`)
 */
export function splitSubmitFailure<K extends string>(
  error: unknown,
  fallback: string,
  fields: Readonly<Record<string, K>>,
): { errors: Partial<Record<K, string>>; failure: string | null } {
  if (!(error instanceof AuthRequestError)) return { errors: {}, failure: fallback }
  const entries = Object.entries(error.fieldErrors)
  if (entries.length === 0) return { errors: {}, failure: error.message }

  const errors: Partial<Record<K, string>> = {}
  const unplaced: string[] = []
  for (const [path, message] of entries) {
    const key = Object.hasOwn(fields, path) ? fields[path] : undefined
    if (key === undefined) unplaced.push(message)
    else if (!errors[key]) errors[key] = message
  }
  return { errors, failure: unplaced[0] ?? null }
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
