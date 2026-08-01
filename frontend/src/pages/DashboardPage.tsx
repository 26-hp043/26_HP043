import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[0]

export function DashboardPage() {
  return (
    <ComingSoon
      screen={screen}
      note="8/8 데모 범위 밖입니다. 항차 단위 결과만 있고 누적 데이터가 없어, 선박 요약을 표시할 근거가 아직 없습니다."
    />
  )
}
