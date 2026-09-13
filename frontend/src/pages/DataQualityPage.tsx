import { PageHeader } from '../components/PageHeader'
import { DataQuality } from '../features/data-quality/DataQuality'
import { DATA_QUALITY_COPY } from '../features/data-quality/copy'
import './DataQualityPage.css'

/**
 * `UIFLOW 2-11` 데이터 점검 — 선대 계층 (#513).
 *
 * 제목은 사이드바와 같은 이름(`screens.ts`)이다. 부제 문구는 `copy.ts`가 소유한다.
 */
export function DataQualityPage() {
  return (
    <div className="data-quality-page">
      <PageHeader screen="DATA_QUALITY">
        <p className="page-head__sub">{DATA_QUALITY_COPY.lead}</p>
      </PageHeader>
      <DataQuality />
    </div>
  )
}
