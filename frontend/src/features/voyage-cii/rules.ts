import type { Rating, RiskLevel } from './types'

/**
 * `PRD`의 등급·위험도 판정 규칙을 그대로 옮긴 순수 함수.
 *
 * **`#39`(등급 판정)·`#40`(위험도)보다 먼저 만들어지는 중복 구현이다.** `#134`가 이를
 * 감수하는 조건이 ⑴ 정본 규칙을 그대로 옮기고 ⑵ Fixture 1로 잠그고 ⑶ 두 이슈 머지 후
 * 대조하는 것이다.
 *
 * demoProvider에서 분리해 둔 이유는 **경계 조건을 정확히 잠그기 위해서다.**
 * `<=`를 `<`로, `>=`를 `>`로 잘못 써도 provider를 통한 요청으로는 그 차이를 드러내는
 * 입력을 만들기 어렵다. 규칙 함수를 직접 호출하면 경계값 자체를 인자로 넣을 수 있다.
 */

export interface Boundaries {
  superior: number
  lower: number
  upper: number
  inferior: number
}

/** `PRD §9.4.1` 위험도 임계값. 등급군마다 다르다. */
export const RISK_THRESHOLD = {
  /** 등급 A·B */
  superiorGrades: 0.05,
  /** 등급 C */
  gradeC: 0.03,
} as const

/**
 * 등급 판정 — `PRD §3.3.6`.
 *
 * ```
 * if attained_CII <= superior_boundary: A
 * else if attained_CII <= lower_boundary: B
 * else if attained_CII <= upper_boundary: C
 * else if attained_CII <= inferior_boundary: D
 * else: E
 * ```
 *
 * **경계값과 정확히 같으면 더 우수한 등급으로 판정한다**(§3.3.6 명시). 그래서 `<=`다.
 */
export function determineRating(attainedCii: number, b: Boundaries): Rating {
  if (attainedCii <= b.superior) return 'A'
  if (attainedCii <= b.lower) return 'B'
  if (attainedCii <= b.upper) return 'C'
  if (attainedCii <= b.inferior) return 'D'
  return 'E'
}

/**
 * 해당 등급에서 **다음 악화 등급으로 넘어가는 경계**.
 * 등급 E는 더 나쁜 등급이 없어 `null`이다.
 */
export function nextWorseBoundary(rating: Rating, b: Boundaries): number | null {
  switch (rating) {
    case 'A':
      return b.superior
    case 'B':
      return b.lower
    case 'C':
      return b.upper
    case 'D':
      return b.inferior
    case 'E':
      return null
  }
}

/**
 * 결정론 화면 위험도 — `PRD §9.4.1` 표를 그대로 옮겼다.
 *
 * | 조건 | 위험도 |
 * |---|---|
 * | 예상 등급 A 또는 B, margin_ratio ≥ 5% | LOW |
 * | 예상 등급 A 또는 B, margin_ratio < 5% | MEDIUM |
 * | 예상 등급 C, margin_ratio ≥ 3% | MEDIUM |
 * | 예상 등급 C, margin_ratio < 3% 또는 예상 등급 D | HIGH |
 * | 예상 등급 E | CRITICAL |
 *
 * **임계값에서 정확히 같으면 완화된 쪽**이다(`≥`). 등급 D·E는 여유율과 무관하다.
 */
export function determineRiskLevel(
  rating: Rating,
  marginRatio: number | null,
): RiskLevel {
  if (rating === 'E') return 'CRITICAL'
  if (rating === 'D') return 'HIGH'
  // 등급 A~C에서 margin_ratio가 없으면 판정 근거가 없다 — 보수적으로 HIGH
  if (marginRatio === null) return 'HIGH'
  if (rating === 'A' || rating === 'B') {
    return marginRatio >= RISK_THRESHOLD.superiorGrades ? 'LOW' : 'MEDIUM'
  }
  return marginRatio >= RISK_THRESHOLD.gradeC ? 'MEDIUM' : 'HIGH'
}
