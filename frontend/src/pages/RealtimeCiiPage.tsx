import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function RealtimeCiiPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.REALTIME_CII}
      note="항해 중 누적 CII와 연말 예상 등급을 확인하는 화면입니다. 선박 상세에서 진행 중인 항차를 선택해 진입합니다."
    />
  )
}
