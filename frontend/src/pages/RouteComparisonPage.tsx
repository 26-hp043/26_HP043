import { useCallback, useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { ScenarioComparison } from '../features/scenario-comparison/ScenarioComparison'
import './RouteComparisonPage.css'

/**
 * UIFLOW 2-2 항로 비교 — 기능②.
 *
 * `#156`이 화면과 demo provider를 채웠다. 실 API(`#57`) 연결은 `#139` 소관이다.
 *
 * 면책 배너를 비교 컴포넌트 밖에 둔다 — `DESIGN_SYSTEM §13` 🔒이 **상시 노출**을
 * 요구하므로, 안에 두면 로딩·실패 상태에서 사라져 안전장치가 결과 유무에 종속된다
 * (`#136`과 같은 판단).
 *
 * UIFLOW 2-2가 기술한 지도 기반 항로 시각화는 8/8 범위 밖이다.
 */
export function RouteComparisonPage() {
  const [disclaimer, setDisclaimer] = useState<string | undefined>(undefined)
  const handleDisclaimer = useCallback((text: string | undefined) => {
    setDisclaimer(text)
  }, [])

  return (
    <div className="route-comparison-page">
      <ScenarioComparison onDisclaimer={handleDisclaimer} />
      <DisclaimerBanner text={disclaimer} />
    </div>
  )
}
