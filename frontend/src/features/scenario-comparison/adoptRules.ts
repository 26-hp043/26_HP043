/*
 * 시나리오 채택 화면의 순수 규칙 (`#580`). 화면(`ScenarioAdoptPanel.tsx`)과 나눈 것은
 * fast refresh 규칙(컴포넌트 파일은 컴포넌트만 내보낸다)과 단위 검사 때문이다.
 */

/** 계획을 바꿀 수 있는 상태 — 서버 `PLANNING_STATUSES`와 같다. */
const PLANNING_STATUSES: ReadonlySet<string> = new Set(['DRAFT', 'PLANNED'])

/** 서버가 덮어쓴 필드 → 화면 이름. */
const FIELD_LABELS: Readonly<Record<string, string>> = {
  planned_distance_nm: '항해거리',
  planned_speed_kn: '평균 속력',
  planned_arrival_at: '도착 예정 시각',
}

/** 채택 전 확인 문구 — 디자인 판정 ③. */
export function adoptConfirmMessage(voyageName: string, scenarioName: string): string {
  return (
    `「${voyageName}」 항차의 계획값(항해거리 · 평균 속력 · 도착 예정 시각)을 ` +
    `「${scenarioName}」 시나리오 값으로 덮어씁니다. 되돌릴 수 없습니다.\n\n` +
    '다른 시나리오를 다시 반영하면 그 값으로 바뀝니다.'
  )
}


/** 계획을 바꿀 수 있는 항차인가 — 서버 `PLANNING_STATUSES`와 같은 집합. */
export function isPlanning(status: string): boolean {
  return PLANNING_STATUSES.has(status)
}

/** 필드 이름. **모르는 필드는 원문을 보인다** — 서버가 필드를 늘렸을 때 조용히 감추지 않는다. */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field
}
