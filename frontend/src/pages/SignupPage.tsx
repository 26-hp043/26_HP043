import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router'
import { AuthAlert, AuthField, AuthShell } from '../features/auth/AuthShell'
import {
  MIN_PASSWORD_LENGTH,
  hasErrors,
  validateSignup,
  type FieldErrors,
} from '../features/auth/authRules'
import { AuthRequestError, LOGIN_PATH, signup, useAuthUser } from '../auth/session'
import { DEFAULT_PATH } from '../screens'

/**
 * 회원가입 — `UIFLOW v2.1` §0-1 (#415).
 *
 * 이 화면은 `v1.0`에서 삭제됐다가 **되살아난 것**이다. 구글 OIDC 도입으로 제품이
 * 비밀번호를 보관하지 않게 되면서 사라졌는데, `#413`의 결정으로 그 전제가 없어졌다.
 *
 * ## 가입하면 바로 로그인된다
 *
 * 서버가 가입 응답에 세션을 함께 발급한다(`API_SPEC §1.2`). 이메일 인증 전에도
 * 이용을 허용하기 때문이며(`PRD §7.10`), 인증은 셸 상단 배너가 안내한다.
 *
 * ## 중복 이메일은 알린다
 *
 * 로그인 실패와 **반대 방향**이다. 감추면 사용자가 가입에 성공했다고 오해한다
 * (`PRD §6.3`의 의도된 비대칭). 서버가 준 문구를 그대로 보여 준다.
 */
export function SignupPage() {
  const user = useAuthUser()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={DEFAULT_PATH} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = validateSignup(email, password, passwordConfirm)
    setErrors(found)
    if (hasErrors(found)) return

    setBusy(true)
    setFailure(null)
    try {
      await signup(email, password, displayName.trim() || null)
      // 성공하면 세션이 발급되어 위 Navigate가 대시보드로 보낸다.
    } catch (error) {
      setFailure(
        error instanceof AuthRequestError
          ? error.message
          : '가입하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="회원가입"
      description="이메일과 비밀번호로 계정을 만듭니다. 가입 후 확인 메일이 발송됩니다."
      footer={
        <>
          이미 계정이 있으신가요? <Link to={LOGIN_PATH}>로그인</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        {failure ? <AuthAlert tone="error">{failure}</AuthAlert> : null}

        <AuthField
          id="signup-email"
          label="이메일"
          type="email"
          value={email}
          onChange={setEmail}
          error={errors.email}
          autoComplete="username"
        />
        <AuthField
          id="signup-password"
          label="비밀번호"
          type="password"
          value={password}
          onChange={setPassword}
          error={errors.password}
          autoComplete="new-password"
          /* 규칙을 입력 도중에 보여 준다 — 제출 후 거부는 다시 입력하게 만든다. */
          hint={`${MIN_PASSWORD_LENGTH}자 이상. 길수록 안전합니다.`}
        />
        <AuthField
          id="signup-password-confirm"
          label="비밀번호 확인"
          type="password"
          value={passwordConfirm}
          onChange={setPasswordConfirm}
          error={errors.passwordConfirm}
          autoComplete="new-password"
        />
        <AuthField
          id="signup-display-name"
          label="이름 (선택)"
          type="text"
          value={displayName}
          onChange={setDisplayName}
          autoComplete="name"
        />

        <button
          className="auth-submit"
          type="submit"
          disabled={busy}
          data-testid="signup-submit"
        >
          {busy ? '가입 중…' : '가입하기'}
        </button>
      </form>
    </AuthShell>
  )
}
