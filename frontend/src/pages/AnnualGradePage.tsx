import { useCallback, useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { AnnualSimulation } from '../features/annual-simulation/AnnualSimulation'
import './AnnualGradePage.css'

/**
 * UIFLOW 2-3 연간 등급 — 기능③.
 *
 * `#157`이 **고정값 목업**으로 채웠다. 계산 엔진(`#63`)과 API(`#64`)는 `2026.10`
 * 마일스톤이며 이 화면은 그 결정을 선점하지 않는다.
 *
 * 면책 배너를 컴포넌트 밖에 둔다 — `DESIGN_SYSTEM §13` 🔒이 **상시 노출**을 요구하므로
 * 안에 두면 로딩·실패 상태에서 사라져 안전장치가 결과 유무에 종속된다(`#136`과 같은 판단).
 */
export function AnnualGradePage() {
  const [disclaimer, setDisclaimer] = useState<string | undefined>(undefined)
  const handleDisclaimer = useCallback((text: string | undefined) => {
    setDisclaimer(text)
  }, [])

  return (
    <div className="annual-grade-page">
      <AnnualSimulation onDisclaimer={handleDisclaimer} />
      <DisclaimerBanner text={disclaimer} />
    </div>
  )
}
