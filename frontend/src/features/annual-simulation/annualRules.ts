import { addFixed, compareFixed } from '../../display/decimal'
import { formatPercent } from '../../display/format'
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
 * ## `Number`로 더하지 않는다 — 십진 문자열로 더한다 (`#820`)
 *
 * 종전에는 `Number(D) + Number(E)`였다. 서버는 4자리로 양자화한 **정확한 십진
 * 문자열**을 보내는데(`TECH_SPEC §2.4`), float으로 더하는 순간 값이 어긋난다.
 *
 * ```text
 * 0.3500 + 0.0500 = 0.39999999999999997   (정확값 0.4)
 * 0.1800 + 0.0200 = 0.19999999999999998   (정확값 0.2)
 * ```
 *
 * 그 결과 **같은 40.0%가 D·E 배분에 따라 주황과 빨강으로 갈리고, 같은 20.0%가 ⚠
 * 유무로 갈렸다.** `runs=5000`이면 확률 단위가 `1/5000`이라 `P(D)=0.3500`·
 * `P(E)=0.0500`은 정상 도달 값이다.
 *
 * :returns: 소수 4자리 십진 문자열. 화면 표기는 `formatPercent`가 만든다.
 */
export function probabilityOfDorE(probabilities: Record<Rating, string>): string {
  return addFixed(probabilities.D ?? '0', probabilities.E ?? '0', PROBABILITY_DIGITS)
}

/** `P(D∪E)` 표기 등급 — `DESIGN_SYSTEM §2.5 (a)`. */
export type RiskFlagTone = 'muted' | 'warning' | 'danger'

/**
 * 확률 문자열의 소수 자릿수 — 서버가 `TECH_SPEC §2.4`대로 4자리로 양자화해 보낸다.
 *
 * 십진 연산의 스케일이며 **표시 자릿수가 아니다.** 화면 표기는 백분율 1자리다
 * (`DESIGN_SYSTEM §4.2`, `formatPercent`).
 */
const PROBABILITY_DIGITS = 4

/** `DESIGN_SYSTEM §2.5 (a)` 위험 임계. 화면이 임의로 정하지 않는다. */
const DANGER_THRESHOLD = '0.4'
const WARNING_THRESHOLD = '0.2'

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
export function riskFlag(pDorE: string): { tone: RiskFlagTone; text: string } {
  /*
   * 임계 비교와 표기를 **둘 다** 십진으로 한다 (`#820`).
   *
   * 종전에는 `pDorE >= 0.4`(float 비교)와 `(pDorE * 100).toFixed(1)`(표기)이었다.
   *
   * * 비교 — `0.3500 + 0.0500`이 `0.39999999999999997`이 되어 **표시된 40.0%가
   *   주황으로** 칠해졌다. `DESIGN_SYSTEM §14`가 요구한 「색 외 보조 채널」인 ⚠
   *   아이콘도 같은 값에서 나타났다 사라졌다 — 색맹 사용자가 의존하는 채널이다.
   * * 표기 — `toFixed`는 정본의 `ROUND_HALF_UP`과 경계에서 갈린다. `'0.1235'`가
   *   여기서는 `12.3%`, `formatPercent`에서는 `12.4%`였다. **바로 아래 `toPercent`가
   *   이 결함을 이미 고쳤는데 이 함수만 옛 경로에 남아 있었다.**
   */
  const pct = formatPercent(pDorE)
  if (compareFixed(pDorE, DANGER_THRESHOLD, PROBABILITY_DIGITS) >= 0) {
    return { tone: 'danger', text: `⚠ P(D/E) ${pct}%` }
  }
  if (compareFixed(pDorE, WARNING_THRESHOLD, PROBABILITY_DIGITS) >= 0) {
    return { tone: 'warning', text: `⚠ P(D/E) ${pct}%` }
  }
  return { tone: 'muted', text: `P(D/E) ${pct}%` }
}

/** 확률 문자열 → 백분율 표시. `DESIGN_SYSTEM §4.2` — 확률은 백분율 1자리. */
export function toPercent(probability: string): string {
  /*
   * `formatPercent`에 위임한다(`DESIGN_SYSTEM §4.2` — 비율·확률 백분율 1자리).
   *
   * 종전에는 `(Number(p) * 100).toFixed(1)`이었다. 같은 1자리지만 **정확히 반올림
   * 경계에 놓인 값에서 답이 갈린다** — `'0.1235'`가 여기서는 `12.3%`, `formatPercent`
   * 에서는 `12.4%`(ROUND_HALF_UP)다. 스택 바 구간 안 문자와 범례가 같은 확률을 두
   * 경로로 그리게 되면서, 그 차이가 **한 화면에 나란히** 보일 수 있게 됐다.
   */
  return `${formatPercent(probability)}%`
}

/**
 * **부호 있는** 확률 변화 → 백분율 표시 (`DESIGN_SYSTEM §4.2` · #822).
 *
 * ## 왜 `toPercent`를 쓸 수 없나
 *
 * `formatPercent`는 앞의 `+`를 **떼어 버린다**(`format.ts` — 음수만 다시 붙인다).
 * 민감도 표의 「달성 확률 변화」는 서버가 `+0.12`/`-0.08`처럼 **부호를 붙여** 보내므로
 * (`services/annual_simulation._signed`), 부호가 사라지면 개선과 악화가 구분되지 않는다.
 *
 * ## 무엇이 문제였나
 *
 * 종전에는 서버 값을 **그대로** 그렸다(`AnnualSimulation.tsx`). 같은 화면 위쪽이
 * `30.0%`(백분율)인데 그 아래 표에 `+0.12`가 놓여, 사용자는 **0.12%p로 읽지만 실제는
 * 12%p**다 — **100배 오독**이다. 열 이름은 「달성 확률 변화」(`copy.ts`)다.
 *
 * `DESIGN_SYSTEM §4.2`가 확률을 「백분율 1자리」로, 비율을 🔒로 규정한다 —
 * *「백분율 환산과 반올림은 표시 시점에만」*.
 */
export function toSignedPercent(change: string): string {
  const trimmed = change.trim()
  const negative = trimmed.startsWith('-')
  // `formatPercent`가 음수 부호는 스스로 붙인다. 양수·0에만 `+`를 얹는다.
  const sign = negative ? '' : '+'
  return `${sign}${formatPercent(trimmed)}%`
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

/**
 * 구간 안에 문자를 넣을 최소 폭 (%) — `DESIGN_SYSTEM §10.2` 원문.
 *
 * *"구간 폭 ≥ 8% 일 때만 내부에 `등급문자 nn%` 표기, 미만은 툴팁으로"*
 */
export const INLINE_LABEL_MIN_PERCENT = 8

/**
 * 이 구간이 **안에** 문자를 담는가.
 *
 * `§10.2`가 정한 8%는 **경계를 포함한다**(`≥`). 정확히 8%인 구간은 안에 넣는다.
 *
 * ## 합이 100%가 아니어도 정규화하지 않는다
 *
 * 판정은 **구간 자신의 폭**만 본다. 서버 확률의 합이 반올림으로 99.9%나 100.1%가
 * 되는 일이 있는데, 그때 100%로 맞춰 늘렸다가는 **화면에 그려진 폭과 판정 근거가
 * 어긋난다** — 8.0%로 그려진 칸이 문자를 못 받거나 그 반대가 된다. 폭이 곧 근거다.
 */
export function showsInlineLabel(percent: number): boolean {
  return percent >= INLINE_LABEL_MIN_PERCENT
}

/** 민감도 표의 행 순서·이름. 서버 키를 화면 순서로 고정한다. */
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
const SENSITIVITY_ROWS: ReadonlyArray<{ key: keyof SensitivityAnalysis; label: string }> = [
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
): Array<{
  key: string
  label: string
  entry: SensitivityEntry
  /**
   * 「달성 확률 변화」 표시 문자열 (#822).
   *
   * **컴포넌트가 아니라 여기서 만든다.** 이 저장소의 관례상 판정은 DOM 없이 검증할
   * 수 있어야 하는데(`realtimeRules.ts` 머리주석), 종전에는 컴포넌트 안 삼항
   * 연산자가 **서버 원값을 그대로** 그렸다 — 검사가 닿지 않는 자리였다.
   */
  probabilityChange: string
}> {
  return SENSITIVITY_ROWS.flatMap(({ key, label }) => {
    const entry = analysis[key]
    if (!entry || typeof entry === 'string') return []
    const change = entry.target_probability_change
    return [
      {
        key: String(key),
        label,
        entry,
        // 확률을 함께 내지 않는 지렛대가 있다(`API_SPEC §6.1`) — 그때는 「—」다.
        // `0`은 값이므로 `??`로 거른다(`||`면 `'0.0000'`이 아니라 빈 문자열이 걸린다).
        probabilityChange: change === null || change === undefined ? '—' : toSignedPercent(change),
      },
    ]
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


