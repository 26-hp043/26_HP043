import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

/**
 * UIFLOW §1-2. 온보딩 흐름(1-1 → 1-2 → 1-3)에 속하므로 사이드바에 노출하지 않는다.
 */
export function VesselRegistrationPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.VESSEL_REGISTRATION}
      note="8/8 데모 범위 밖입니다. 기능① 화면이 고정 샘플 선박 목록을 쓰므로(#135) 선박 등록 없이 시연할 수 있습니다. 선박 API는 #50 · #51 · #52입니다."
    />
  )
}
