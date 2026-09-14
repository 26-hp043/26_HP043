import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { PageHeader } from '../components/PageHeader'
import { FleetReduction } from '../features/fleet-reduction/FleetReduction'
import { FLEET_REDUCTION_COPY } from '../features/fleet-reduction/copy'
import './FleetReductionPage.css'

/**
 * `UIFLOW 2-10` 함대 감축 계획 — 선대 계층 (#513).
 *
 * 제목은 사이드바와 같은 이름(`screens.ts`)이다. 부제 문구는 `copy.ts`가 소유한다.
 *
 * 면책 배너를 컴포넌트 밖에 둔다 — `DESIGN_SYSTEM §13` 🔒 **상시 노출**이라 안에 두면 로딩·실패
 * 상태에서 사라진다(`AnnualGradePage`와 같은 판단 · #1071). 서버가 `disclaimer`를 보내지 않으므로
 * `PRD §6.3` 기본 문구를 쓴다.
 */
export function FleetReductionPage() {
  return (
    <div className="fleet-reduction-page">
      <PageHeader screen="FLEET_REDUCTION">
        <p className="page-head__sub">{FLEET_REDUCTION_COPY.lead}</p>
      </PageHeader>
      <FleetReduction />
      <DisclaimerBanner />
    </div>
  )
}
