import { VesselDetail } from '../features/vessel-detail/VesselDetail'

/**
 * `UIFLOW v2.0` 2-8 선박 상세 — 3계층의 허리.
 *
 * 대시보드(선대) 카드에서 내려오고, 진행 중 항차가 있으면 실시간 CII(항차)로
 * 내려간다. 페이지는 자리만 잡고 내용은 `features/vessel-detail`이 소유한다.
 */
export function VesselDetailPage() {
  return <VesselDetail />
}
