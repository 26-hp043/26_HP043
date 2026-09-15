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

/**
 * 채택이 무효화한 계산 결과 수를 **사람이 읽는 한 문장**으로 (`#1077` · `API_SPEC §5.2`).
 *
 * 「없음」이 세 종류라 셋을 **다르게** 적는다 — 같은 모양으로 그리면 사용자는 가장 나쁜
 * 해석을 고른다.
 *
 * | 값 | 뜻 | 문장 |
 * |---|---|---|
 * | `undefined` | 서버가 수를 싣지 않았다 — **알 수 없다** | 수를 말하지 않고 사실만 |
 * | `0` | **새로** 표시된 것이 없다. 정본상 「계산 이력이 없다」와 「이미 전부 표시돼 있다」 둘 다일 수 있다 | 둘 중 하나로 단정하지 않는다 |
 * | `n > 0` | `n`건에 표시가 붙었다 | 수를 적는다 |
 *
 * ⚠️ **`0`을 「무효화된 계산이 없습니다」로 적지 않는다.** 이미 전부 표시된 상태에서도 `0`이
 * 나오므로(`API_SPEC §5.2` 명시), 그렇게 적으면 「옛 계산이 아직 유효하다」로 읽힌다 — 이
 * 표시가 막으려던 바로 그 오해다.
 */
export function invalidatedMessage(count: number | undefined): string {
  const base = '계획이 바뀌어 이 항차의 기존 계산 결과는 다시 계산해야 합니다.'
  if (count === undefined) {
    return base
  }
  if (count === 0) {
    return `${base} 이번에 새로 재계산 필요 표시가 붙은 계산 결과는 없습니다 — 이 항차에 계산 이력이 없거나, 이미 전부 표시돼 있습니다.`
  }
  return `${base} 이 항차의 계산 결과 ${count}건에 재계산 필요 표시를 남겼습니다.`
}
