import { useCallback, useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { PageHeader } from '../components/PageHeader'
import { AnnualSimulation } from '../features/annual-simulation/AnnualSimulation'
import { ANNUAL_COPY } from '../features/annual-simulation/copy'
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
      {/*
        제목은 사이드바와 같은 이름(`screens.ts`)을 쓴다. 종전에는 이 화면만
        「연간 CII 시뮬레이션」을 `h2`(20px)로 달고 있어, **누른 이름과 도착한
        이름이 다르고 크기도 한 단 작았다.**

        부제 문구는 `copy.ts`에 있다 — 금지 표현 가드가 검사하는 자리다.
      */}
      <PageHeader screen="ANNUAL_GRADE">
        <p className="page-head__sub">{ANNUAL_COPY.lead}</p>
      </PageHeader>
      <AnnualSimulation onDisclaimer={handleDisclaimer} />
      <DisclaimerBanner text={disclaimer} />
    </div>
  )
}
