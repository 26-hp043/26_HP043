import { ComingSoon } from '../components/ComingSoon'
import { SCREEN_BY_ID } from '../screens'

export function MainboardPage() {
  return (
    <ComingSoon
      screen={SCREEN_BY_ID.MAINBOARD}
      note="보유 선박 전체의 CII 등급과 위험 선박을 한 화면에서 확인하는 화면입니다."
    />
  )
}
