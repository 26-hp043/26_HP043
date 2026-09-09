import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { LOGIN_PATH, probeCurrentUser, useAuthResolved, useAuthUser } from './session'

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
  const resolved = useAuthResolved()
  const location = useLocation()

  useEffect(() => {
    void probeCurrentUser()
  }, [])

  /*
   * **확인 전에는 판정하지 않는다** (`#825` ⑴).
   *
   * 첫 렌더에서 `currentUser`는 언제나 `null`이고 프로브는 `useEffect`라 커밋
   * **이후**에 돈다. 그 한 프레임 때문에 로그인 상태로 새로고침할 때마다 주소가
   * `/login?next=…`로 바뀌며 **로그인 카드가 그려졌다가 되돌아왔다.**
   *
   * 위 주석이 이미 규정한 동작이다 — *「확인 중에는 자식을 렌더하지 않되 레이아웃을
   * 유지한다」*. 구현이 빠져 있었을 뿐이다.
   *
   * 빈 화면을 그리지 않고 **자리만 잡는다** — `aria-busy`로 확인 중임을 알린다.
   */
  if (!resolved) {
    return <div className="require-auth__pending" aria-busy="true" />
  }

  if (!user) {
    /*
     * 해시까지 싣는다 (`#825` ⑴ 곁가지). 종전에는 `pathname + search`뿐이라
     * `#fleet-actions` 같은 앵커가 복귀에서 사라졌다 — 사용자가 있던 자리는
     * 해시까지가 한 벌이다.
     */
    const next = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to={`${LOGIN_PATH}?next=${encodeURIComponent(next)}`} replace />
  }
  return <>{children}</>
}
