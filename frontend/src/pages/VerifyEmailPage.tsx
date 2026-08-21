import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { AuthAlert, AuthShell } from '../features/auth/AuthShell'
import {
  AuthRequestError,
  LOGIN_PATH,
  confirmEmailVerification,
  useAuthUser,
} from '../auth/session'
import { DEFAULT_PATH } from '../screens'

/**
 * 이메일 인증 — `UIFLOW v2.1` 0-4 (#415).
 *
 * 메일 링크(`/verify-email?token=…`)로 진입한다. 토큰이 있으면 **도착 즉시 검증**을
 * 시도한다 — 사용자가 링크를 눌러 도착한 상태에서 버튼을 한 번 더 누르게 하는 것은
 * 이유 없는 단계다.
 *
 * ## 실패 사유를 나누지 않는다
 *
 * 서버가 「없음」·「만료」·「이미 사용됨」을 같은 문구로 준다(`#408`). 화면도 그대로
 * 보여 주며, 다시 요청할 경로를 함께 안내한다.
 */
export function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const user = useAuthUser()

  const [state, setState] = useState<'idle' | 'working' | 'ok' | 'failed'>(
    token ? 'working' : 'idle',
  )
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    let alive = true

    confirmEmailVerification(token)
      .then((text) => {
        if (!alive) return
        setMessage(text)
        setState('ok')
      })
      .catch((error: unknown) => {
        if (!alive) return
        setMessage(
          error instanceof AuthRequestError
            ? error.message
            : '인증을 처리하지 못했습니다.',
        )
        setState('failed')
      })

    return () => {
      alive = false
    }
  }, [token])

  if (!token) {
    return (
      <AuthShell
        title="이메일 인증"
        description="가입 시 보내 드린 메일의 링크를 눌러 주세요."
        footer={<Link to={LOGIN_PATH}>로그인으로 돌아가기</Link>}
      >
        <AuthAlert tone="ok">
          메일이 오지 않았다면 로그인 후 상단 배너에서 재발송할 수 있습니다.
        </AuthAlert>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      title="이메일 인증"
      footer={
        state === 'ok' ? (
          <Link to={user ? DEFAULT_PATH : LOGIN_PATH}>
            {user ? '대시보드로 이동' : '로그인하기'}
          </Link>
        ) : (
          <Link to={LOGIN_PATH}>로그인으로 돌아가기</Link>
        )
      }
    >
      {state === 'working' ? (
        <p className="auth-description" aria-busy="true">
          인증을 확인하고 있습니다…
        </p>
      ) : null}

      {state === 'ok' && message ? <AuthAlert tone="ok">{message}</AuthAlert> : null}

      {state === 'failed' && message ? (
        <>
          <AuthAlert tone="error">{message}</AuthAlert>
          <p className="auth-description" style={{ marginTop: 'var(--spacing-lg)' }}>
            로그인하시면 상단 배너에서 인증 메일을 다시 받을 수 있습니다.
          </p>
        </>
      ) : null}
    </AuthShell>
  )
}
