import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function AnnualGradePage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.ANNUAL_GRADE}
      issues={['#157 목업 화면']}
      note="계산 엔진(#63)과 API(#64)는 2026.10 마일스톤입니다. #157은 고정값 목업이며 실제 계산을 하지 않습니다."
    />
  )
}
