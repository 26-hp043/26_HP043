import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { LOGIN_PATH, authGuardEnabled, probeCurrentUser, useAuthUser } from './session'

/**
 * 라우트 가드 — `UIFLOW.md` §0 진입 조건 (#278).
 *
 * *"유효한 세션이 없는 상태에서 어떤 화면에 접근하든 `0. 로그인 화면`으로 이동한다."*
 *
 * - 마운트 시 세션을 프로브한다. 비인증(401·네트워크 실패 모두)이면 로그인으로
 *   보내고 `?next=`에 현재 경로를 싣는다 — 로그인 성공 시 그 경로로 복귀한다.
 * - **demo 모드(`VITE_USE_API !== "true"`)에서는 렌더를 즉시 허용한다.** 백엔드가
 *   없는 환경에서 가드가 화면을 막으면 안 되기 때문이다(session.ts 참조).
 * - 확인 중(프로브 pending)에는 자식을 렌더하지 않되 레이아웃을 유지한다 —
 *   깜빡임으로 로그인 화면을 잠깐 보여주는 것보다 낫다.
 * - 로그아웃 등으로 캐시된 사용자가 사라지면 즉시 리다이렉트한다(세션 만료 대응).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const user = useAuthUser()
  const location = useLocation()

  useEffect(() => {
    void probeCurrentUser()
  }, [])

  if (!authGuardEnabled()) return <>{children}</>
  if (!user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`${LOGIN_PATH}?next=${encodeURIComponent(next)}`} replace />
  }
  return <>{children}</>
}
