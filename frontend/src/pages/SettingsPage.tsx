import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function SettingsPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.SETTINGS}
      note="8/8 데모 범위 밖입니다. 계정 관리는 인증 도입 이후이며, 파라미터 조회 API 계약은 아직 API_SPEC에 없습니다."
    />
  )
}
