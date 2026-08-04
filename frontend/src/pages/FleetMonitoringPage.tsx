import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function FleetMonitoringPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.FLEET_MONITORING}
      note="8/8 데모 범위 밖입니다. UIFLOW 2-4가 요구하는 실시간 위치·운항 상태는 AIS 연동이 선행되어야 하며 현재 계획된 백엔드 이슈가 없습니다."
    />
  )
}
