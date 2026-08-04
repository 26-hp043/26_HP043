import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function ReportsPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.REPORTS}
      note="8/8 데모 범위 밖입니다. 내보내기 백엔드는 #59입니다. CSV 가져오기(#60)를 이 화면에 둘지는 팀 확인 대기 중입니다."
    />
  )
}
