import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { AuthAlert, AuthField, AuthShell } from '../features/auth/AuthShell'
import { ErrorState } from '../components/ErrorState'
import { PAGE_FAILURE_MESSAGE, actionFailureTitle } from '../components/errorCopy'
import { hasErrors, safeNext, splitSubmitFailure, validateLogin } from '../features/auth/authRules'
import type { FieldErrors } from '../features/auth/authRules'
import {
  LOGIN_PATH,
  PASSWORD_RESET_PATH,
  SIGNUP_PATH,
  login,
  tourLogin,
  useAuthUser,
} from '../auth/session'

/** 서버 필드 경로 → 이 폼의 칸 (#877 ⑴). */
const LOGIN_SERVER_FIELDS = { email: 'email', password: 'password' } as const

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
  /*
   * 둘러보기 링크 (`#1486`). 코드는 링크에 실려 오며, **버튼의 존재 자체가
   * 기능을 알리므로** 코드가 없으면 버튼을 렌더하지 않는다 — 아래 `submitTour`가
   * 아니라 렌더 분기에서 막는다.
   *
   * **첫 렌더에 한 번만 읽고 state로 들고 있는다** (`#1495`). 바로 아래에서 주소창의
   * `?tour=`를 지우기 때문에, 매 렌더 `searchParams`를 다시 읽으면 두 번째 렌더에서
   * 코드가 사라져 버튼이 없어진다.
   */
  const [tourCode] = useState(() => searchParams.get('tour'))

  /*
   * 공개 둘러보기 스위치 (#1486 후속).
   *
   * 링크에 코드가 없어도 버튼을 보인다 — 평가자·인터뷰 대상자가 **주소만 알면** 들어올 수
   * 있어야 하기 때문이다. 이 값은 **불리언**이고 접근 코드가 아니다. 코드를 `VITE_`로
   * 넣으면 빌드 산출물에 그대로 인라인되어 「비밀 링크」보다 못한 상태가 된다 — 문을 여는
   * 판정은 서버의 `TOUR_PUBLIC`이 한다.
   *
   * 그래도 안전한 이유는 **둘러보기 세션이 읽기 전용**이기 때문이다
   * (`auth/tour_policy.py`) — 문이 넓어져도 권한은 넓어지지 않는다.
   */
  const tourIsPublic = import.meta.env.VITE_TOUR_PUBLIC === 'true'
  const showTour = tourIsPublic || tourCode !== null

  /*
   * 주소창에서 코드를 지운다 (`#1495`).
   *
   * 코드는 URL에 실려 오므로 **브라우저 히스토리·북마크·화면 공유·뒤로가기**에 그대로
   * 남는다. 인터뷰 자리에서 화면을 함께 보는 일이 잦아, 지우지 않으면 **의도하지 않은
   * 사람에게 관리자 세션을 여는 열쇠가 그대로 보인다.**
   *
   * `replaceState`라 히스토리 항목을 **늘리지 않고 덮는다** — 뒤로가기로 코드가 있는
   * 주소로 돌아가지 않는다. 읽기는 위에서 이미 끝났으므로 기능에는 영향이 없다.
   */
  useEffect(() => {
    if (!tourCode) return
    try {
      window.history.replaceState(null, '', LOGIN_PATH)
    } catch {
      // 히스토리 조작이 막힌 환경(일부 내장 브라우저)에서도 로그인은 그대로 된다.
    }
  }, [tourCode])

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
      // 서버가 짚은 칸은 그 입력칸에, 나머지는 폼 위에 (#877 ⑴).
      const next = splitSubmitFailure(
        error,
        '로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.',
        LOGIN_SERVER_FIELDS,
      )
      setErrors(next.errors)
      setFailure(next.failure)
    } finally {
      setBusy(false)
    }
  }

  /**
   * 둘러보기 링크 코드로 로그인한다. 실패 문구는 서버가 준 그대로 보인다 —
   * 「꺼져 있음」과 「코드 불일치」를 같은 문구로 내는 것이 백엔드의 규칙이라,
   * 화면이 따로 지어내면 그 규칙이 깨진다.
   */
  const submitTour = async () => {
    if (!showTour) return
    setBusy(true)
    setFailure(null)
    try {
      await tourLogin(tourCode)
      // 성공하면 `useAuthUser`가 갱신되어 위 Navigate가 처리한다.
    } catch (error) {
      const next = splitSubmitFailure(error, '둘러보기 링크로 로그인하지 못했습니다.', {})
      setFailure(next.failure)
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

      {showTour ? (
        <button
          className="auth-secondary"
          type="button"
          disabled={busy}
          onClick={() => void submitTour()}
          data-testid="tour-submit"
        >
          {busy ? '둘러보기 여는 중…' : '로그인 없이 둘러보기'}
        </button>
      ) : null}

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
 *
 * ## 층위는 A(페이지)가 아니라 영역이다 (`#1053` · 2026-09-17 확정)
 *
 * 2026-09-11 확정 C ⑶은 이 화면을 **A층위 이관 대상**으로 두었는데, A층위 제목은
 * **고정** 「화면을 불러오지 못했습니다」다(확정 B — 제목은 호출부가 쓰지 않는다).
 * 그런데 이 화면은 **화면이 안 뜬 것이 아니라 로그인이 실패한 것**이고,
 * `ErrorState`가 스스로 적어 둔 층위 정의도 *「`page` — 화면 전체가 뜨지 않았다」*다.
 *
 * 그래서 **영역 실패의 「처리」 갈래**를 쓴다 — `actionFailureTitle('로그인')`이
 * 「로그인에 실패했습니다」를 만든다. A층위에 제목 예외를 만들지 않아도 되고,
 * 제목이 **호출부의 문자열이 아니라 확정된 기계에서** 나온다.
 *
 * 제목은 `AuthShell`의 `<h1>`이 이미 그 자리를 갖고 있으므로 `size="compact"`를
 * 쓴다 — 블록으로 두면 한 화면에 제목이 둘이 된다.
 */
export function LoginFailurePage() {
  const navigate = useNavigate()

  /*
   * 본문은 페이지 실패 기본 본문과 같은 문장이다(`PRD §6.4`) — 이 화면의 문장이
   * 기본값의 출처였고, 한 문장 안에 「주세요」와 「주십시오」가 섞여 있어 통일했다.
   * 재시도 버튼 문구 「다시 시도」는 `ErrorState`가 준다(모든 층위 단일 문구).
   */
  return (
    <AuthShell title={actionFailureTitle('로그인')}>
      <ErrorState
        level="region"
        size="compact"
        message={PAGE_FAILURE_MESSAGE}
        onRetry={() => void navigate(LOGIN_PATH)}
      />
    </AuthShell>
  )
}
