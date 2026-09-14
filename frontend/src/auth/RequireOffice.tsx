import type { ReactNode } from 'react'
import { ErrorState } from '../components/ErrorState'
import { OFFICE_ONLY_SCREEN_NOTICE } from '../features/auth/authRules'
import { isOffice, useAuthUser } from './session'

/**
 * 사무직 전용 화면 가드 (`UIFLOW §2.2` 역할 열 · `API_SPEC §1.2` · `#672`).
 *
 * `RequireAuth` **안쪽**에서 쓴다 — 세션은 이미 확인된 상태고, 여기서 보는 것은 역할뿐이다.
 *
 * ## 로그인으로 보내지 않는다
 *
 * 비인증은 「다시 로그인하면 된다」이지만 현장직은 다시 로그인해도 같다. 이동시키면
 * 사용자는 「왜 튕겼지」로 받는다. 자리에서 **왜 못 쓰는지**를 말하고 끝낸다 —
 * 서버가 `403 FORBIDDEN_ROLE`로 막는 것과 같은 답을 화면이 먼저 한다.
 *
 * ## 사이드바와 짝이다
 *
 * `AppShell`은 `officeOnly` 화면을 현장직에게 **「사무직 전용」 뱃지의 비활성 항목**으로
 * 보인다. 그래도 주소를 직접 치면 여기까지 온다 — 두 겹이 같은 판정을 한다.
 */
export function RequireOffice({ children }: { children: ReactNode }) {
  const user = useAuthUser()
  if (isOffice(user)) return <>{children}</>
  return (
    <div className="page">
      <ErrorState level="page" message={OFFICE_ONLY_SCREEN_NOTICE} />
    </div>
  )
}
