import { AccountPanel } from '../features/account/AccountPanel'
import { SCREEN_BY_ID } from '../screens'

/**
 * 설정 화면 — `UIFLOW 2-6` (`#506`).
 *
 * ## 계정 관리로 좁혀 넣는다
 *
 * `UIFLOW`가 이 화면을 「판정 보류」로 둔 것은 `#359`(어드민 계정·권한 도입 범위)가
 * 미결이기 때문이다. **자기 계정 관리는 권한과 무관하므로** `PRD §5` 계정 관리 MUST
 * 근거로 먼저 넣는다. 조직·권한·규제 파라미터 설정은 `#359`가 정해질 때 붙인다 —
 * 그래야 정본 개정이 선행하지 않는다.
 */
export function SettingsPage() {
  const screen = SCREEN_BY_ID.SETTINGS

  return (
    <>
      <header className="acc__head">
        <h1 className="acc__title">
          {screen.label}{' '}
          <span className="acc__title-en" lang="en">
            {screen.labelEn}
          </span>
        </h1>
      </header>

      <AccountPanel />
    </>
  )
}
