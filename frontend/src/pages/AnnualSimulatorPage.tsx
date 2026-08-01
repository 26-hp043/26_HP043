import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[4]

export function AnnualSimulatorPage() {
  return (
    <ComingSoon
      screen={screen}
      issues={['#157 목업 화면']}
      note="계산 엔진(#63)과 API(#64)는 2026.10 마일스톤입니다. #157은 고정값 목업이며 실제 계산을 하지 않습니다."
    />
  )
}
