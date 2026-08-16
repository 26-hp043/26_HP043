import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function ReportsPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.REPORTS}
      note="항차 완료 리포트와 연간 실적 리포트를 PDF·CSV로 내려받는 화면입니다."
    />
  )
}
