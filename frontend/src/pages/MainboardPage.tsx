import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function MainboardPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.MAINBOARD}
      issues={['#351']}
      note="선대 계층 중심 화면입니다. 선박 카드 그리드·경고 배너는 #351이, 경고 문구는 #352(원문 대조 후 확정)가 제공합니다."
    />
  )
}
