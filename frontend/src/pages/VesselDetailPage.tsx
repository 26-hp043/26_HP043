import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function VesselDetailPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.VESSEL_DETAIL}
      note="선박별 연도별 CII 이력과 올해 누적(YTD) 등급을 확인하는 화면입니다."
    />
  )
}
