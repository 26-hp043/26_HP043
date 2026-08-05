import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function RouteComparisonPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.ROUTE_COMPARISON}
      issues={['#156 비교 화면 + demo provider', '#139 실 API 연결']}
      note="UIFLOW 2-2가 기술한 지도 기반 항로 시각화는 8/8 범위 밖입니다."
    />
  )
}
