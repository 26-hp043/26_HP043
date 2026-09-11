import { useState, type FormEvent } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router'
import { AuthAlert, AuthField, AuthShell } from '../features/auth/AuthShell'
import { PAGE_FAILURE_MESSAGE } from '../components/errorCopy'
import { hasErrors, safeNext, validateLogin } from '../features/auth/authRules'
import type { FieldErrors } from '../features/auth/authRules'
import {
  AuthRequestError,
  LOGIN_PATH,
  PASSWORD_RESET_PATH,
  SIGNUP_PATH,
  login,
  useAuthUser,
} from '../auth/session'

/**
 * 로그인 화면 — `UIFLOW v2.1` §0 (#415).
 *
 * ## 구글 버튼이 사라졌다
 *
 * `#413`~`#414`로 자체 이메일·비밀번호 인증이 됐다. 종전에는 백엔드 OIDC 진입점으로
 * **전체 페이지 이동**했으나, 이제 로그인은 앱 안에서 끝난다.
 *
 * ## 실패 문구를 화면이 만들지 않는다
 *
 * 서버가 준 문구를 그대로 보여 준다. 「없는 이메일」과 「틀린 비밀번호」를 같은
 * 문구로 내는 것이 **계정 존재 여부를 숨기는 규칙**(`API_SPEC §1.2`)이고, 화면이
 * 다시 쓰면 그 규칙이 깨질 수 있다.
 */
export function LoginPage() {
  const [searchParams] = useSearchParams()
  const user = useAuthUser()
  const next = safeNext(searchParams.get('next'))

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={next} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = validateLogin(email, password)
    setErrors(found)
    if (hasErrors(found)) return

    setBusy(true)
    setFailure(null)
    try {
      await login(email, password)
      // 성공하면 `useAuthUser`가 갱신되어 위 Navigate가 처리한다.
    } catch (error) {
      /*
       * 서버 422의 `details[].field`는 해당 입력창 아래에 붙인다 (#877) — 데이터
       * 경계 9곳과 같은 계약. 필드를 못 가리키는 실패(INVALID_CREDENTIALS 포함)는
       * 배너 한 줄로 나간다.
       */
      const authError = error instanceof AuthRequestError ? error : null
      const field = authError?.field
      if (authError && (field === 'email' || field === 'password')) {
        const message = authError.message
        setErrors((prev) => ({ ...prev, [field]: message }))
      } else {
        setFailure(authError?.message ?? '로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      /*
       * 종전 제목은 「중소선사를 위한 선대 CII 관리」였고 설명문이 서비스 소개였다.
       * 둘 다 **브랜드 판으로 옮겼다**(`intro`) — 카드 제목은 이 카드가 무엇을
       * 하는 곳인지 적는 자리다(`#608`).
       */
      title="로그인"
      disclaimer
      intro
      footer={
        <>
          계정이 없으신가요? <Link to={SIGNUP_PATH}>회원가입</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        {failure ? <AuthAlert tone="error">{failure}</AuthAlert> : null}

        <AuthField
          id="login-email"
          label="이메일"
          type="email"
          value={email}
          onChange={setEmail}
          error={errors.email}
          autoComplete="username"
        />
        <AuthField
          id="login-password"
          label="비밀번호"
          type="password"
          value={password}
          onChange={setPassword}
          error={errors.password}
          autoComplete="current-password"
        />

        <button
          className="auth-submit"
          type="submit"
          disabled={busy}
          data-testid="login-submit"
        >
          {busy ? '로그인 중…' : '로그인'}
        </button>
      </form>

      <p className="auth-links">
        <Link to={PASSWORD_RESET_PATH}>비밀번호를 잊으셨나요?</Link>
      </p>
    </AuthShell>
  )
}

/**
 * 로그인 실패 화면 — `UIFLOW v2.1` 0-2.
 *
 * 자체 인증에서는 실패가 로그인 화면 안에서 표시되므로 이 화면으로 오는 경로는
 * 드물다. 세션 발급 자체가 실패한 경우를 위해 남긴다.
 */
export function LoginFailurePage() {
  /*
   * 본문은 페이지 실패 기본 본문과 같은 문장이다(`PRD §6.4`) — 이 화면의 문장이
   * 기본값의 출처였고, 한 문장 안에 「주세요」와 「주십시오」가 섞여 있어 통일했다.
   * 버튼 문구도 재시도 단일 문구 「다시 시도」다(종전 「다시 시도하기」).
   */
  return (
    <AuthShell title="로그인하지 못했습니다" description={PAGE_FAILURE_MESSAGE}>
      <Link className="auth-submit auth-submit--link" to={LOGIN_PATH}>
        다시 시도
      </Link>
    </AuthShell>
  )
}
