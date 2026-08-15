import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function RealtimeCiiPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.REALTIME_CII}
      issues={['#357']}
      note="선박 상세(2-8)에서 진행 중 항차 선택 시 진입하는 항차 계층 화면입니다. 3종 값 정의는 #358이 PRD에 확정합니다."
    />
  )
}
