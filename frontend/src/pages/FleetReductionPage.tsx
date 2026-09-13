import { PageHeader } from '../components/PageHeader'
import { FleetReduction } from '../features/fleet-reduction/FleetReduction'
import { FLEET_REDUCTION_COPY } from '../features/fleet-reduction/copy'
import './FleetReductionPage.css'

/**
 * `UIFLOW 2-10` 함대 감축 계획 — 선대 계층 (#513).
 *
 * 제목은 사이드바와 같은 이름(`screens.ts`)이다. 부제 문구는 `copy.ts`가 소유한다.
 */
export function FleetReductionPage() {
  return (
    <div className="fleet-reduction-page">
      <PageHeader screen="FLEET_REDUCTION">
        <p className="page-head__sub">{FLEET_REDUCTION_COPY.lead}</p>
      </PageHeader>
      <FleetReduction />
    </div>
  )
}
