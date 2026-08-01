import { ComingSoon } from '../components/ComingSoon'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { SCREENS } from '../screens'
import './VoyageCiiPage.css'

const screen = SCREENS[2]

/**
 * 기능① 항차 CII 추정 — 8/8 데모의 주 화면이자 기본 진입 경로다.
 * 입력 폼은 #135, 결과 표시는 #136이 채운다. 이 이슈(#133)는 자리만 만든다.
 */
export function VoyageCiiPage() {
  return (
    <div className="voyage-cii-page">
      <ComingSoon
        screen={screen}
        issues={['#134 타입·demo provider', '#135 입력 폼', '#136 결과 화면']}
        note="8/8 데모의 주 경로입니다. 기본 진입 경로로 지정되어 있습니다."
      />
      <DisclaimerBanner />
    </div>
  )
}
