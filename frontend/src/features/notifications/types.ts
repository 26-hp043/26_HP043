/**
 * 알림 — 지금 걸려 있는 상태 목록 (`API_SPEC §2.19` · #2204).
 *
 * 발생 기록이 아니다 — 읽음 · 안 읽음 · 발생 시각이 없다. 해결되면 다음 조회에서 사라진다.
 */
type NotificationKind =
  | 'CORRECTIVE_ACTION'
  | 'D_ENTRY_SOON'
  | 'UNCONFIRMED_VOYAGE'
  | 'ESTIMATED_VALUES'

/** 단계 둘 — 위험(규제 의무) · 확인 필요(자료 정리). `DESIGN_SYSTEM §7.2` 「알림」. */
export type NotificationLevel = 'RISK' | 'CHECK'

/**
 * 알림 한 줄. 필드는 종류마다 일부만 찬다(`§2.19` 각주) — 나머지는 `null`이다.
 * 문구는 화면이 만든다(`notificationRules.ts`).
 */
export interface NotificationItem {
  kind: NotificationKind
  level: NotificationLevel
  vesselId: string
  vesselName: string
  /** `CORRECTIVE_ACTION`만 — `E_THIS_YEAR` · `D_THIRD_YEAR`. */
  reason: string | null
  /** `D_ENTRY_SOON`만 — 남은 일수. */
  days: number | null
  /** `UNCONFIRMED_VOYAGE`만. */
  voyageId: string | null
  voyageNo: string | null
  /** `ESTIMATED_VALUES`만 — 그 선박의 데이터 점검 행 수. */
  count: number | null
}

export interface NotificationSnapshot {
  counts: { risk: number; check: number; total: number }
  /** **서버가 정한 순서**다(단계 → 종류). 화면은 다시 정렬하지 않는다. */
  items: NotificationItem[]
}
