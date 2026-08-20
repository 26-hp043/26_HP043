import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { LOGIN_PATH, probeCurrentUser, useAuthUser } from './session'

/**
 * 라우트 가드 — `UIFLOW.md` §0 진입 조건 (#278).
 *
 * *"유효한 세션이 없는 상태에서 어떤 화면에 접근하든 `0. 로그인 화면`으로 이동한다."*
 *
 * - 마운트 시 세션을 프로브한다. 비인증(401·네트워크 실패 모두)이면 로그인으로
 *   보내고 `?next=`에 현재 경로를 싣는다 — 로그인 성공 시 그 경로로 복귀한다.
 * - **가드는 항상 켜져 있다** (#542). 종전에는 demo 모드에서 렌더를 즉시 허용했는데,
 *   그 우회가 데모인 줄 모르고 쓰게 만든 원인이었다(`#528`). 데모 폐기로 사라졌다.
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

  if (!user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`${LOGIN_PATH}?next=${encodeURIComponent(next)}`} replace />
  }
  return <>{children}</>
}
