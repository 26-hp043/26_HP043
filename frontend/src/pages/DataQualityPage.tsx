import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { PageHeader } from '../components/PageHeader'
import { DataQuality } from '../features/data-quality/DataQuality'
import { DATA_QUALITY_COPY } from '../features/data-quality/copy'
import './DataQualityPage.css'

/**
 * `UIFLOW 2-11` 데이터 점검 — 선대 계층 (#513).
 *
 * 제목은 사이드바와 같은 이름(`screens.ts`)이다. 부제 문구는 `copy.ts`가 소유한다.
 *
 * 면책 배너를 컴포넌트 밖에 둔다 — `DESIGN_SYSTEM §13` 🔒 **상시 노출**이라 안에 두면 로딩·실패
 * 상태에서 사라진다(`AnnualGradePage`와 같은 판단 · #1071). 서버가 `disclaimer`를 보내지 않으므로
 * `PRD §6.3` 기본 문구를 쓴다.
 */
export function DataQualityPage() {
  return (
    <div className="data-quality-page">
      <PageHeader screen="DATA_QUALITY">
        <p className="page-head__sub">{DATA_QUALITY_COPY.lead}</p>
      </PageHeader>
      <DataQuality />
      <DisclaimerBanner />
    </div>
  )
}
