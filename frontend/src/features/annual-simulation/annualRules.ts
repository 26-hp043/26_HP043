import type { Rating } from '../voyage-cii/types'
import type { MonteCarloBlock, SensitivityAnalysis, SensitivityEntry } from './types'

/**
 * 기능③ 화면의 표시 규칙 (#442).
 *
 * ## 판정을 여기서 하지 않는다
 *
 * 위험도(`risk_level`)는 서버가 확정한다 — `PRD §9.4.2`가 기능③의 위험도를 **목표 달성
 * 확률 기반**으로 규정하고, 서버가 `calculate_probability_risk`로 낸다. 화면이 확률을
 * 보고 다시 판정하면 **두 곳이 갈리고 그 차이는 눈으로 발견되지 않는다.**
 *
 * 이 모듈이 하는 것은 **정본이 화면 소관으로 남긴 것**뿐이다 — `P(D∪E)` 파생과
 * 그 표기 임계(`DESIGN_SYSTEM §2.5 (a)`).
 */

/** 등급 표시 순서. 확률 스택 바와 표가 같은 순서를 써야 한다. */
export const RATING_ORDER: readonly Rating[] = ['A', 'B', 'C', 'D', 'E'] as const

/**
 * `P(D∪E)` — `PRD §12.5`가 정의한 파생값.
 *
 * ```text
 * P(D∪E) = P(D) + P(E)
 * ```
 *
 * **`1 − success`로 계산하지 않는다.** `PRD §12.5`가 그 여사건 관계는 **목표가 C일
 * 때만** 성립한다고 못박는다. 목표가 B인 화면에서 `1 − success`를 쓰면 C 확률까지
 * 위험으로 세어 값이 부풀려진다.
 *
 * 문자열 확률을 숫자로 바꾸는 유일한 자리다. 표시용 파생이라 Layer 1 정밀도가 필요하지
 * 않다 — 화면에 나가는 값은 백분율 1자리다(`DESIGN_SYSTEM §4.2`).
 */
export function probabilityOfDorE(probabilities: Record<Rating, string>): number {
  return Number(probabilities.D ?? 0) + Number(probabilities.E ?? 0)
}

/** `P(D∪E)` 표기 등급 — `DESIGN_SYSTEM §2.5 (a)`. */
export type RiskFlagTone = 'muted' | 'warning' | 'danger'

/**
 * `DESIGN_SYSTEM §2.5 (a)` 위험도 표기.
 *
 * | 조건 | 표기 | 색 |
 * |---|---|---|
 * | `P(D∪E) < 20%` | `P(D/E) 12%` | text-muted |
 * | `20% ≤ P(D∪E) < 40%` | `⚠ P(D/E) 28%` | Warning |
 * | `P(D∪E) ≥ 40%` | `⚠ P(D/E) 47%` | Danger |
 *
 * > 임계값 20% / 40%는 정본이 **초안값**으로 표시한 것이며 실운항 데이터 확보 후
 * > 재조정한다(`DESIGN_SYSTEM §16`). **지금 따를 규칙은 위 표**이므로 그대로 옮긴다 —
 * > 임계를 화면이 임의로 정하면 재조정 때 어디를 고쳐야 하는지 알 수 없다.
 */
export function riskFlag(pDorE: number): { tone: RiskFlagTone; text: string } {
  const pct = (pDorE * 100).toFixed(1)
  if (pDorE >= 0.4) return { tone: 'danger', text: `⚠ P(D/E) ${pct}%` }
  if (pDorE >= 0.2) return { tone: 'warning', text: `⚠ P(D/E) ${pct}%` }
  return { tone: 'muted', text: `P(D/E) ${pct}%` }
}

/** 확률 문자열 → 백분율 표시. `DESIGN_SYSTEM §4.2` — 확률은 백분율 1자리. */
export function toPercent(probability: string): string {
  return `${(Number(probability) * 100).toFixed(1)}%`
}

/**
 * 확률 스택 바의 구간 — `DESIGN_SYSTEM §10.2`.
 *
 * 폭이 0인 구간도 **목록에서 빼지 않는다.** 화면이 A~E 다섯 등급을 항상 같은 순서로
 * 보여야, 두 실행을 나란히 놓고 비교할 수 있다.
 */
export function stackSegments(
  probabilities: Record<Rating, string>,
): Array<{ rating: Rating; percent: number; label: string }> {
  return RATING_ORDER.map((rating) => {
    const raw = Number(probabilities[rating] ?? 0)
    return { rating, percent: raw * 100, label: toPercent(probabilities[rating] ?? '0') }
  })
}

/** 민감도 표의 행 순서·이름. 서버 키를 화면 순서로 고정한다. */
export const SENSITIVITY_ROWS: ReadonlyArray<{ key: keyof SensitivityAnalysis; label: string }> = [
  { key: 'speed_minus_1kn', label: '속력 −1kn' },
  { key: 'speed_plus_1kn', label: '속력 +1kn' },
  { key: 'fuel_minus_10pct', label: '연료 −10%' },
  { key: 'fuel_plus_10pct', label: '연료 +10%' },
  { key: 'distance_minus_5pct', label: '거리 −5%' },
  { key: 'distance_plus_5pct', label: '거리 +5%' },
  { key: 'voyage_minus_1', label: '잔여 항차 −1' },
  { key: 'voyage_plus_1', label: '잔여 항차 +1' },
  { key: 'fuel_cf_alternative', label: '대체 연료' },
] as const

/**
 * 응답에 실제로 담긴 민감도 행만 골라낸다.
 *
 * 서버가 변수마다 다른 필드를 담고 **일부는 아예 생략한다**(잔여 항차가 없으면 항차
 * 변수를 낼 수 없다). 빈 행을 표에 남기면 「값이 0」으로 읽힌다.
 */
export function sensitivityRows(
  analysis: SensitivityAnalysis,
): Array<{ key: string; label: string; entry: SensitivityEntry }> {
  return SENSITIVITY_ROWS.flatMap(({ key, label }) => {
    const entry = analysis[key]
    if (!entry || typeof entry === 'string') return []
    return [{ key: String(key), label, entry }]
  })
}

/**
 * 재현성 요약 문구 — `TECH_SPEC §5.2`.
 *
 * seed와 생성기를 **한 줄로** 보여 준다. 「이 seed로 다시 실행하면 같은 값이 나온다」가
 * 이 화면의 계약이므로, seed가 화면에 없으면 그 계약을 확인할 방법이 없다.
 */
export function reproducibilityLine(mc: MonteCarloBlock): string {
  return `${mc.rng_metadata.bit_generator} · seed ${mc.rng_metadata.seed_entropy} · ${mc.runs}회`
}


