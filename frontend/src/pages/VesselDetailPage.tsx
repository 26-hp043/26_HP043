import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function VesselDetailPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.VESSEL_DETAIL}
      issues={['#356']}
      note="대시보드(2-4) 선박 카드 선택 시 진입하는 선박 계층 화면입니다. 연도별 이력·YTD 조회 API는 #354·#355가 제공합니다."
    />
  )
}
