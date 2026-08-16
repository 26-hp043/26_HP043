import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

/**
 * UIFLOW §1-2. 온보딩 흐름(1-1 → 1-2 → 1-3)에 속하므로 사이드바에 노출하지 않는다.
 */
export function VesselRegistrationPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.VESSEL_REGISTRATION}
      note="선박 제원을 직접 등록하는 화면입니다. 현재는 등록된 선박 목록에서 선택해 이용하실 수 있습니다."
    />
  )
}
