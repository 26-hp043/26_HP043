import { SCREEN_BY_ID } from '../../screens'
import { VESSEL_QUERY_KEY, CURRENT_VOYAGE_SEGMENT, vesselPath, voyagePath } from '../../layout/globalContext'
import { daysValueText, riskReasonText } from '../fleet/fleetRules'
import { voyageActualsPath } from '../voyage-management/voyageRules'
import type { RiskReason } from '../fleet/types'
import type { NotificationItem, NotificationLevel } from './types'

/**
 * 알림 한 줄의 글자와 행동 링크 (`DESIGN_SYSTEM §7.2` 「알림」 · #2204).
 *
 * ## 문구를 새로 짓지 않는다
 *
 * 시정조치계획 사유는 대시보드 「조치 필요」와 같은 `riskReasonText`, 남은 일수는 대시보드
 * 「D등급 진입 임박」 칸과 같은 `daysValueText`를 쓴다. 같은 사실이 두 자리에서 다른 말을
 * 하면 어느 쪽이 맞는지부터 묻게 된다.
 *
 * ## 링크는 그 사실을 가장 자세히 보는 화면으로 — 해당 선박이 선택된 채로
 *
 * | 종류 | 이동 |
 * |---|---|
 * | 시정조치계획 대상 | 연간 등급 관리 (`?vessel_id=` — 쿼리로 선박을 담는 화면이다) |
 * | D등급 진입 임박 | 실시간 CII (`/vessels/{id}/voyages/current` — 진행 중 항차) |
 * | 실적 확정 전 항차 | 선박 상세의 그 항차 실적 입력 (`?actuals=`) |
 * | 실측이 아닌 값 | 데이터 점검 — **선대 단위 화면**이라 선박을 고르는 자리가 없다. 그 선박의 행은 목록에서 찾는다 |
 *
 * 링크 글자는 갈 곳의 이름이다(`§8` 결과 카드 「다음 행동」과 같은 규칙) — 「~하세요」가 아니다.
 */

/** 단계 글자 — 색은 CSS가 Danger/Warning 글자색으로 준다. 색만으로 말하지 않는다(`§14`). */
export const LEVEL_LABEL: Record<NotificationLevel, string> = {
  RISK: '위험',
  CHECK: '확인 필요',
}

/** 한 줄 사실. */
export function notificationFact(item: NotificationItem): string {
  switch (item.kind) {
    case 'CORRECTIVE_ACTION':
      return riskReasonText(item.reason as RiskReason)
    case 'D_ENTRY_SOON':
      return `D등급 진입까지 ${item.days === null ? '—' : daysValueText(item.days)}`
    case 'UNCONFIRMED_VOYAGE':
      return item.voyageNo ? `항차 ${item.voyageNo} 실적 확정 전` : '실적 확정 전 항차'
    case 'ESTIMATED_VALUES':
      return `실측이 아닌 값 ${item.count ?? 0}건`
  }
}

/** 행동 링크 — 갈 곳과 그 이름. */
export function notificationAction(item: NotificationItem): { to: string; label: string } {
  switch (item.kind) {
    case 'CORRECTIVE_ACTION':
      return {
        to: `${SCREEN_BY_ID.ANNUAL_GRADE.path}?${new URLSearchParams({ [VESSEL_QUERY_KEY]: item.vesselId })}`,
        label: SCREEN_BY_ID.ANNUAL_GRADE.label,
      }
    case 'D_ENTRY_SOON':
      return {
        to: voyagePath(item.vesselId, CURRENT_VOYAGE_SEGMENT),
        label: SCREEN_BY_ID.REALTIME_CII.label,
      }
    case 'UNCONFIRMED_VOYAGE':
      return {
        to: item.voyageId ? voyageActualsPath(item.vesselId, item.voyageId) : vesselPath(item.vesselId),
        label: SCREEN_BY_ID.VESSEL_DETAIL.label,
      }
    case 'ESTIMATED_VALUES':
      return { to: SCREEN_BY_ID.DATA_QUALITY.path, label: SCREEN_BY_ID.DATA_QUALITY.label }
  }
}
