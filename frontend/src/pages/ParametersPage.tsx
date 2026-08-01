import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[5]

export function ParametersPage() {
  return (
    <ComingSoon
      screen={screen}
      note="8/8 데모 범위 밖입니다. 파라미터 조회 API 계약이 아직 API_SPEC에 없어 화면 구현의 선행 조건이 갖춰지지 않았습니다."
    />
  )
}
