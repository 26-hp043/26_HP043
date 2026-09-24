import { useCallback, useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { PageHeader } from '../components/PageHeader'
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
 * 위치 맥락 지도는 `ScenarioComparison` 안의 `VoyageRouteMap`이 그린다(`#1265` ·
 * `UIFLOW 2-2`) — 좌표가 모두 있을 때만이고, 이 페이지는 관여하지 않는다.
 */
export function RouteComparisonPage() {
  const [disclaimer, setDisclaimer] = useState<string | undefined>(undefined)
  const handleDisclaimer = useCallback((text: string | undefined) => {
    setDisclaimer(text)
  }, [])

  return (
    <div className="route-comparison-page">
      <PageHeader screen="ROUTE_COMPARISON">
        <p className="page-head__sub">
          직항·우회·감속 시나리오를 같은 기준으로 비교합니다.
        </p>
      </PageHeader>
      <ScenarioComparison onDisclaimer={handleDisclaimer} />
      <DisclaimerBanner text={disclaimer} />
    </div>
  )
}
