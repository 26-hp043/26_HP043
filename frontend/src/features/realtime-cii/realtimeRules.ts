import type { RealtimeCii } from './types'

/**
 * 실시간 CII 화면 규칙 (`#357`).
 *
 * 컴포넌트에서 분리한 이유는 이 저장소의 다른 feature와 같다 — **판정은 DOM 없이
 * 검증할 수 있어야 한다.** vitest에 DOM 환경이 없다.
 */

/**
 * 폴링 간격 (ms).
 *
 * **60초로 정한 근거.** 값은 시계에 따라 연속적으로 변하지만, 사람이 보는 화면에서
 * 의미 있게 달라지는 단위는 시간이다 — 14 kn · 30 t/day인 배가 1분에 만드는 것은
 * 0.23 nm와 0.02 t이고, 소수 6자리 CII의 끝자리에서나 보인다. 더 짧게 잡으면
 * 서버 부하만 늘고 화면은 같아 보인다.
 *
 * 반대로 더 길게 잡으면 「정박을 시작했는데 화면이 한참 그대로」가 된다. 정박은
 * 등급을 실제로 움직이는 사건이라 그 지연이 이 화면의 목적을 깎는다.
 */
export const POLL_INTERVAL_MS = 60_000

/**
 * 「없는 것」의 사유 문구.
 *
 * **사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.** 서버가 준 코드를 사람 말로
 * 옮기되, 모르는 코드가 오면 코드를 그대로 보여 준다 — 빈칸보다 낫다.
 */
export const PROJECTION_REASONS: Readonly<Record<string, string>> = {
  NO_BASIS:
    '올해 실적이 아직 없어 연말 예상을 산출할 수 없습니다. 항차 실적을 입력하면 계산됩니다.',
  YEAR_COMPLETE: '해당 연도가 끝나 연말 예상 대신 확정 누적값을 보시면 됩니다.',
}

/**
 * 경고 코드의 사람 말.
 *
 * `SIMULATION_NO_FUEL_*`는 **행동을 안내해야 한다.** 「값이 안 변한다」로만 적으면
 * 사용자는 기다리고, 실제로는 제원을 채워야 한다.
 */
export const WARNING_TEXT: Readonly<Record<string, string>> = {
  REFERENCE_ONLY: '본 화면의 값은 참고용 예측값이며 규제 제출용 공식 결과가 아닙니다.',
  SIMULATION_NO_FUEL_RATE:
    '선박에 기준 일일 연료소모량이 등록되지 않아 진행 중 항차분이 누적에 반영되지 않았습니다. 선박 제원을 입력해 주세요.',
  SIMULATION_NO_FUEL_TYPE:
    '진행 중 항차의 연료 종류를 알 수 없어 진행분이 누적에 반영되지 않았습니다. 항차에 연료를 입력하거나 선박 기본 연료를 지정해 주세요.',
  COMPLETED_NO_FUEL:
    '완료된 항차 일부에 실적 연료가 없어 계획값으로 대신 계산했습니다.',
}

export function warningText(code: string): string {
  return WARNING_TEXT[code] ?? code
}

export function projectionReason(code: string | null): string {
  if (code === null) return '연말 예상을 산출할 수 없습니다.'
  return PROJECTION_REASONS[code] ?? code
}

/**
 * 정박 중인가.
 *
 * **`underway_state`만 본다.** 「진행 중 항차가 없다」로 판정하면 항차를 아직
 * 등록하지 않은 선박이 전부 정박 중으로 보인다 — 기록이 없는 것과 정박한 것은
 * 다르다(`#356`의 `stateText`와 같은 판단).
 */
export function isNotUnderWay(data: RealtimeCii): boolean {
  return data.underwayState === 'NOT_UNDER_WAY'
}

/**
 * 정박이 등급을 실제로 밀고 있는가 — **명세 3-③이 보이라고 한 것**.
 *
 * 정박 상태인 것만으로는 부족하다. 정박 **연료가 기록되어 있어야** 분자 `M`이
 * 늘고, 그때 비로소 등급이 악화된다. 기록이 없으면 정박해도 값은 그대로다 —
 * 그 상태를 「악화 중」으로 그리면 화면이 사실과 다른 말을 한다.
 *
 * `#370`이 만든 입력 경로가 바로 이 조건을 채우는 곳이다.
 */
export function isDegradingAtBerth(data: RealtimeCii): boolean {
  return isNotUnderWay(data) && data.ytd.notUnderwayPeriodCount > 0
}

/**
 * 진행 중 항차의 남은 거리.
 *
 * 계획 거리에서 누적 거리를 뺀다. **음수는 0으로 자른다** — 계획보다 더 간 항차는
 * 실제로 생기고(우회·기상), 「남은 거리 −120 nm」는 아무 뜻도 없다.
 *
 * 계획 거리가 없으면 `null`이다. 0으로 두면 「다 왔다」로 읽힌다.
 */
export function remainingDistanceNm(data: RealtimeCii): number | null {
  const voyage = data.currentVoyage
  if (!voyage || voyage.plannedDistanceNm === null || voyage.distanceNm === null) {
    return null
  }
  const planned = Number(voyage.plannedDistanceNm)
  const done = Number(voyage.distanceNm)
  if (Number.isNaN(planned) || Number.isNaN(done)) return null
  return Math.max(0, Number((planned - done).toFixed(2)))
}

/** 진행률(0~1). 계획 거리가 없거나 0이면 `null` — 분모 0을 화면이 만들지 않는다. */
export function voyageProgressRatio(data: RealtimeCii): number | null {
  const voyage = data.currentVoyage
  if (!voyage || voyage.plannedDistanceNm === null || voyage.distanceNm === null) {
    return null
  }
  const planned = Number(voyage.plannedDistanceNm)
  const done = Number(voyage.distanceNm)
  if (!Number.isFinite(planned) || planned <= 0 || !Number.isFinite(done)) return null
  return Math.min(1, Math.max(0, done / planned))
}

/**
 * ⑴ 대비 ⑶의 방향 — 「좋아지는 중 / 나빠지는 중 / 같음」.
 *
 * 둘 중 하나라도 없으면 `null`이다. 없는 값을 「같음」으로 뭉치면 화면이 근거 없이
 * 안심시킨다.
 */
export function projectionDirection(
  data: RealtimeCii,
): 'IMPROVING' | 'WORSENING' | 'FLAT' | null {
  const now = data.ytd.attainedCii
  const end = data.projection.attainedCii
  if (now === null || end === null) return null

  const a = Number(now)
  const b = Number(end)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  // CII는 **낮을수록 좋다.** 부호를 뒤집어 읽으면 화면이 정반대를 말한다.
  if (b < a) return 'IMPROVING'
  if (b > a) return 'WORSENING'
  return 'FLAT'
}

/** 기준 시각 표시. 실시간 화면에서는 값 자체만큼 중요한 정보다. */
export function formatAsOf(asOf: string): string {
  return new Date(asOf).toLocaleString('ko-KR', { hour12: false })
}
