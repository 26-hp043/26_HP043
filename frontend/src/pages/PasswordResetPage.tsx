import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AuthAlert, AuthField, AuthShell } from '../features/auth/AuthShell'
import {
  MIN_PASSWORD_LENGTH,
  hasErrors,
  validateEmail,
  validatePassword,
  type FieldErrors,
} from '../features/auth/authRules'
import {
  AuthRequestError,
  LOGIN_PATH,
  confirmPasswordReset,
  requestPasswordReset,
} from '../auth/session'

/**
 * 비밀번호 찾기 — `UIFLOW v2.1` §0-3 (#415).
 *
 * **한 경로에 두 화면이 있다.**
 *
 * | 진입 | 화면 |
 * |---|---|
 * | `/password-reset` | ⑴ 요청 — 이메일을 넣고 재설정 메일을 받는다 |
 * | `/password-reset?token=…` | ⑵ 재설정 — 메일 링크로 들어와 새 비밀번호를 넣는다 |
 *
 * 경로를 나누지 않은 이유는 **메일 링크가 곧 이 경로**이기 때문이다. 별도 경로를
 * 두면 링크를 잘못 만들었을 때 사용자가 404를 만난다.
 *
 * ## 요청 결과가 가입 여부를 드러내지 않는다
 *
 * 서버가 가입 여부와 무관하게 같은 문구를 준다(`API_SPEC §1.2`). 화면은 그 문구를
 * 그대로 보여 주며, 「가입되지 않은 주소입니다」 같은 판단을 하지 않는다.
 */
export function PasswordResetPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  return token ? <ResetForm token={token} /> : <RequestForm />
}

/** ⑴ 재설정 메일 요청. */
function RequestForm() {
  const [email, setEmail] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [done, setDone] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const emailError = validateEmail(email)
    setErrors(emailError ? { email: emailError } : {})
    if (emailError) return

    setBusy(true)
    setFailure(null)
    try {
      setDone(await requestPasswordReset(email))
    } catch (error) {
      setFailure(
        error instanceof AuthRequestError
          ? error.message
          : '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="비밀번호 찾기"
      description="가입하신 이메일 주소를 입력하시면 재설정 링크를 보내 드립니다."
      footer={<Link to={LOGIN_PATH}>로그인으로 돌아가기</Link>}
    >
      {done ? (
        /* 서버 문구를 그대로 쓴다 — 가입 여부를 드러내지 않기 위한 문구다. */
        <AuthAlert tone="ok">{done}</AuthAlert>
      ) : (
        <form className="auth-form" onSubmit={submit} noValidate>
          {failure ? <AuthAlert tone="error">{failure}</AuthAlert> : null}

          <AuthField
            id="reset-email"
            label="이메일"
            type="email"
            value={email}
            onChange={setEmail}
            error={errors.email}
            autoComplete="username"
          />
          <button
            className="auth-submit"
            type="submit"
            disabled={busy}
            data-testid="reset-request-submit"
          >
            {busy ? '보내는 중…' : '재설정 링크 받기'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}

/** ⑵ 메일 링크로 진입한 새 비밀번호 설정. */
function ResetForm({ token }: { token: string }) {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [done, setDone] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found: FieldErrors = {}
    const passwordError = validatePassword(password)
    if (passwordError) found.password = passwordError
    if (password !== passwordConfirm) {
      found.passwordConfirm = '비밀번호가 일치하지 않습니다.'
    }
    setErrors(found)
    if (hasErrors(found)) return

    setBusy(true)
    setFailure(null)
    try {
      setDone(await confirmPasswordReset(token, password))
    } catch (error) {
      setFailure(
        error instanceof AuthRequestError
          ? error.message
          : '비밀번호를 변경하지 못했습니다.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="새 비밀번호 설정"
      description="새 비밀번호를 입력해 주세요. 변경하면 로그인된 모든 기기에서 로그아웃됩니다."
      footer={<Link to={LOGIN_PATH}>로그인으로 돌아가기</Link>}
    >
      {done ? (
        <>
          <AuthAlert tone="ok">{done}</AuthAlert>
          <button
            className="auth-submit"
            type="button"
            onClick={() => navigate(LOGIN_PATH)}
            style={{ marginTop: 'var(--spacing-lg)', inlineSize: '100%' }}
          >
            로그인하기
          </button>
        </>
      ) : (
        <form className="auth-form" onSubmit={submit} noValidate>
          {failure ? <AuthAlert tone="error">{failure}</AuthAlert> : null}

          <AuthField
            id="reset-password"
            label="새 비밀번호"
            type="password"
            value={password}
            onChange={setPassword}
            error={errors.password}
            autoComplete="new-password"
            hint={`${MIN_PASSWORD_LENGTH}자 이상. 길수록 안전합니다.`}
          />
          <AuthField
            id="reset-password-confirm"
            label="새 비밀번호 확인"
            type="password"
            value={passwordConfirm}
            onChange={setPasswordConfirm}
            error={errors.passwordConfirm}
            autoComplete="new-password"
          />
          <button
            className="auth-submit"
            type="submit"
            disabled={busy}
            data-testid="reset-confirm-submit"
          >
            {busy ? '변경 중…' : '비밀번호 변경'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}
