import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function SettingsPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.SETTINGS}
      note="계정·조직 설정과 규제 파라미터 조회를 이 화면에서 제공할 예정입니다."
    />
  )
}
