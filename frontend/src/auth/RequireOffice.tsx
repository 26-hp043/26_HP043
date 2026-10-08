import type { ReactNode } from 'react'
import { Lock } from 'lucide-react'
import { Icon } from '../components/Icon'
import '../components/ErrorState.css'
import { OFFICE_ONLY_SCREEN_NOTICE, OFFICE_ONLY_SCREEN_TITLE } from '../features/auth/authRules'
import { isOffice, useAuthUser } from './session'

/**
 * 사무직 전용 화면 가드 (`UIFLOW §2.2` 역할 열 · `API_SPEC §1.2` · `#672` · `#1301`).
 *
 * `RequireAuth` **안쪽**에서 쓴다 — 세션은 이미 확인된 상태고, 여기서 보는 것은 역할뿐이다.
 * **관리자도 통과한다** — `isOffice()`가 ADMIN을 참으로 보므로(`#1301`, ADMIN은 OFFICE의
 * 상위집합) 여기서 따로 갈라 주지 않아도 된다. 막히는 것은 현장직뿐이다.
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
  /*
   * 실패가 아니라 **권한 안내**다 (#2352) — `ErrorState`(제목 고정 「화면을 불러오지 못했습니다」 ·
   * `role="alert"`)를 쓰지 않는다. 모양은 페이지 층위 블록을 그대로 빌리고, 낭독은 경보가 아니라
   * 상태(`role="status"`)로 · 아이콘은 경고 삼각형 대신 자물쇠로 둔다. 다시 시도해도 같으므로 재시도도 없다.
   */
  return (
    <div className="page">
      <div className="error-state error-state--page" role="status">
        <Icon glyph={Lock} className="error-state__icon" />
        <div className="error-state__body">
          <p className="error-state__title">{OFFICE_ONLY_SCREEN_TITLE}</p>
          <p className="error-state__message">{OFFICE_ONLY_SCREEN_NOTICE}</p>
        </div>
      </div>
    </div>
  )
}
