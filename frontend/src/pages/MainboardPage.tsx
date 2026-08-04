import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function MainboardPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.MAINBOARD}
      note="8/8 데모 범위 밖입니다. 항차 단위 결과만 있고 누적 데이터가 없어 선박 상태 요약을 표시할 근거가 아직 없습니다."
    />
  )
}
