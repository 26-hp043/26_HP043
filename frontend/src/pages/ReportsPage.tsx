import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function ReportsPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.REPORTS}
      issues={['#360', '#361', '#362']}
      note="MVP 승격 화면입니다(#344). PRD 보고서 절은 #360, 생성 API·PDF 렌더링은 #361이 제공합니다."
    />
  )
}
