import { VesselRegistration } from '../features/vessel-registration/VesselRegistration'

/**
 * 선박 등록 화면 (`UIFLOW §1-2` · `PRD §6.2 SCR-002` · #441).
 *
 * 온보딩 흐름(1-1 → 1-2 → 1-3)에 속하므로 사이드바에 노출하지 않는다
 * (`screens.ts`의 `OFF_NAV_ORDER`).
 */
export function VesselRegistrationPage() {
  return <VesselRegistration />
}
