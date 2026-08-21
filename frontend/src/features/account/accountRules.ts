import { MIN_PASSWORD_LENGTH, validatePassword } from '../auth/authRules'

/**
 * 계정 관리 규칙 — `API_SPEC §1.2` (`#506`).
 *
 * ## 비밀번호 검증을 다시 쓰지 않는다
 *
 * `authRules.validatePassword`가 서버 `auth/password.py`의 길이 제약과 같은 값을
 * 이미 들고 있다. 여기서 따로 두면 **두 곳이 서로 모른 채 갈라진다** — 가입 화면과
 * 변경 화면이 다른 규칙을 적용하는 상태가 조용히 생긴다.
 *
 * ## 이메일은 여기 없다
 *
 * `PATCH /auth/me`는 `display_name`만 받고, `email`을 보내면 서버가 `extra="forbid"`로
 * **422 거부**한다. 이메일은 로그인 ID이자 `idx_app_user_email`의 키라 잘못 바꾸면
 * 계정에 접근할 수 없다(재설정 메일도 그 주소로 간다). 화면은 읽기 전용으로 보이고
 * `EMAIL_IMMUTABLE_NOTICE`를 함께 낸다.
 */

/**
 * 표시 이름 최대 길이.
 *
 * 서버 스키마와 같은 값이어야 한다. 길이 제약이 화면에만 있으면 사용자는
 * **저장 단계에서야** 거부를 만난다.
 */
export const MAX_DISPLAY_NAME_LENGTH = 100

/**
 * 표시 이름 검증.
 *
 * **빈 값을 허용한다** — `display_name`은 nullable이고, 이름을 지우는 것도
 * 정당한 조작이다. 빈 문자열을 보내면 서버가 무엇으로 읽을지 모호하므로
 * `displayNamePayload`가 `null`로 바꾼다.
 */
export function validateDisplayName(name: string): string | undefined {
  if (name.length > MAX_DISPLAY_NAME_LENGTH) {
    return `표시 이름은 ${MAX_DISPLAY_NAME_LENGTH}자를 넘을 수 없습니다.`
  }
  return undefined
}

/** `PATCH /auth/me` 본문. 빈 이름은 `null`로 보낸다 — 「지운다」는 뜻이다. */
export function displayNamePayload(name: string): { display_name: string | null } {
  const trimmed = name.trim()
  return { display_name: trimmed === '' ? null : trimmed }
}

/**
 * 비밀번호 변경 폼의 오류 키.
 *
 * `authRules.FieldErrors`를 쓰지 않는다 — 그쪽은 `email`·`password`·`passwordConfirm`
 * **세 키로 닫힌 인터페이스**라 여기 키를 담을 수 없다. 인덱스 시그니처로 열어 두면
 * 로그인·가입 폼에서 오타 난 키가 조용히 통과하므로, **폼마다 자기 키를 선언한다.**
 */
export interface AccountFieldErrors {
  currentPassword?: string
  newPassword?: string
  confirmPassword?: string
}

export function hasAccountErrors(errors: AccountFieldErrors): boolean {
  return Object.values(errors).some(Boolean)
}

export interface PasswordChangeDraft {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

/**
 * 비밀번호 변경 검증 — `POST /auth/password-change`.
 *
 * 현재 비밀번호가 맞는지는 **서버만 안다.** 화면은 형식만 본다.
 *
 * 새 비밀번호가 현재와 같은지도 여기서 잡는다 — 서버가 받아 주더라도
 * **세션만 전량 무효화되고 바뀐 것은 없는** 상태가 되어 사용자가 손해만 본다.
 */
export function validatePasswordChange(draft: PasswordChangeDraft): AccountFieldErrors {
  const errors: AccountFieldErrors = {}

  if (draft.currentPassword === '') {
    errors.currentPassword = '현재 비밀번호를 입력해 주세요.'
  }

  const newError = validatePassword(draft.newPassword)
  if (newError) errors.newPassword = newError

  if (draft.confirmPassword !== draft.newPassword) {
    errors.confirmPassword = '새 비밀번호가 서로 다릅니다.'
  }

  if (
    !errors.newPassword &&
    draft.currentPassword !== '' &&
    draft.newPassword === draft.currentPassword
  ) {
    errors.newPassword = '현재 비밀번호와 다른 비밀번호를 입력해 주세요.'
  }

  return errors
}

/**
 * 비밀번호를 바꾸면 **본인도 로그아웃된다.**
 *
 * `API_SPEC §1.2` — 변경 성공 시 기존 세션을 전량 무효화한다. 탈취된 상태에서
 * 비밀번호만 바꾸면 공격자 세션이 그대로 살아 있기 때문이고, 그 규칙에는
 * 변경을 요청한 본인의 세션도 포함된다.
 *
 * **미리 고지하지 않으면 사용자는 「왜 튕겼지」로 받는다.**
 */
export const PASSWORD_CHANGE_NOTICE =
  '비밀번호를 바꾸면 이 기기를 포함해 로그인된 모든 기기에서 로그아웃됩니다. 새 비밀번호로 다시 로그인해 주세요.'

export { MIN_PASSWORD_LENGTH }
