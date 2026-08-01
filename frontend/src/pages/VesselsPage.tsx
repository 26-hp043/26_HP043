import { ComingSoon } from '../components/ComingSoon'
import { SCREENS } from '../screens'

const screen = SCREENS[1]

export function VesselsPage() {
  return (
    <ComingSoon
      screen={screen}
      note="8/8 데모 범위 밖입니다. 기능① 화면은 고정 샘플 선박 목록을 쓰므로(#135) 선박 등록·수정 화면 없이 시연할 수 있습니다. 선박 API는 #50 · #51 · #52입니다."
    />
  )
}
