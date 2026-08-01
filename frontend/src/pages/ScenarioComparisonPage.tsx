import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[3]

export function ScenarioComparisonPage() {
  return (
    <ComingSoon
      screen={screen}
      issues={['#156 비교 화면 + demo provider', '#139 실 API 연결']}
    />
  )
}
