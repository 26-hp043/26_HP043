import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[6]

export function DataIoPage() {
  return (
    <ComingSoon
      screen={screen}
      note="8/8 데모 범위 밖입니다. CSV 내보내기는 #59, 가져오기는 #60입니다."
    />
  )
}
