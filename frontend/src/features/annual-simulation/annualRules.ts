import { addFixed, compareFixed } from '../../display/decimal'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatGrouped,
  formatPercent,
  formatTimestamp,
} from '../../display/format'
import type { Rating } from '../voyage-cii/types'
import type { MonteCarloBlock, SensitivityAnalysis, SensitivityEntry } from './types'
import { ANNUAL_COPY } from './copy'

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
export function riskFlag(
  pDorE: string,
): { tone: RiskFlagTone; withIcon: boolean; text: string } {
  /*
   * 임계 비교와 표기를 **둘 다** 십진으로 한다 (`#820`).
   *
   * 종전에는 `pDorE >= 0.4`(float 비교)와 `(pDorE * 100).toFixed(1)`(표기)이었다.
   *
   * * 비교 — `0.3500 + 0.0500`이 `0.39999999999999997`이 되어 **표시된 40.0%가
   *   주황으로** 칠해졌다. `DESIGN_SYSTEM §14`가 요구한 「색 외 보조 채널」인 ⚠
   *   아이콘도 같은 값에서 나타났다 사라졌다 — 색맹 사용자가 의존하는 채널이다.
   *
   *   ⚠ 글리프는 **문자열에서 뺐다** (`#935`). `§2.5`가 그것을 「임시 글리프」로
   *   두고 아이콘 세트 확정 시 교체하라 했고, 세트는 Lucide로 확정됐다. 이 함수는
   *   **아이콘을 붙일지 말지(`withIcon`)만 정하고** 형태는 화면이 그린다 —
   *   `voyage-cii/resultRules.ts`의 `riskLabel`이 쓰는 것과 같은 형태다.
   * * 표기 — `toFixed`는 정본의 `ROUND_HALF_UP`과 경계에서 갈린다. `'0.1235'`가
   *   여기서는 `12.3%`, `formatPercent`에서는 `12.4%`였다. **바로 아래 `toPercent`가
   *   이 결함을 이미 고쳤는데 이 함수만 옛 경로에 남아 있었다.**
   */
  const pct = formatPercent(pDorE)
  if (compareFixed(pDorE, DANGER_THRESHOLD, PROBABILITY_DIGITS) >= 0) {
    return { tone: 'danger', withIcon: true, text: `P(D/E) ${pct}%` }
  }
  if (compareFixed(pDorE, WARNING_THRESHOLD, PROBABILITY_DIGITS) >= 0) {
    return { tone: 'warning', withIcon: true, text: `P(D/E) ${pct}%` }
  }
  return { tone: 'muted', withIcon: false, text: `P(D/E) ${pct}%` }
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
): Array<{ rating: Rating; percent: number; label: string; inline: boolean; empty: boolean }> {
  return RATING_ORDER.map((rating) => {
    const value = probabilities[rating] ?? '0'
    const raw = Number(value)
    const shownPercent = Number(formatPercent(value))
    return {
      // 그리는 폭은 float 그대로 쓴다 — 반올림하면 칸들의 합이 100%에서 더 벌어진다.
      percent: raw * 100,
      /*
       * **바에 그리지 않는 구간** (#1096 ⑵). 화면에 「0.0%」로 쓰이는 구간은 폭이 없어
       * 보이지 않는데, 종전에는 툴팁·`tabIndex`가 붙어 **보이지 않는 요소에 초점이
       * 두 번** 갔다(A 0% · E 0%). 범례에는 그대로 남는다 — 다섯 등급의 순서와 값은
       * 거기서 읽는다. 판정 근거는 `inline`과 같이 **화면에 쓰인 숫자**다.
       */
      empty: shownPercent === 0,
      /*
       * **판정을 여기서 끝낸다** (#846).
       *
       * 화면에 값을 넘겨 거기서 판정하게 두면, 넘기는 값을 `percent`로 바꾸는 것만으로
       * 결함이 되살아나고 **순수 함수 검사는 그것을 잡지 못한다**(실제로 돌연변이
       * 검사에서 확인했다). 고를 수 있는 값이 하나뿐이면 틀릴 수가 없다.
       *
       * 근거는 **화면에 쓰인 숫자**다. `percent`는 float 곱셈이고 `label`은
       * ROUND_HALF_UP이라 경계에서 갈린다: `'0.0795'`는 `7.949999…`이면서 표시는
       * `8.0%`다. 종전 판정은 **「8.0%」라고 쓰인 칸을 8% 미만으로 취급**해 문자를
       * 툴팁으로 밀었다. 사용자가 읽는 근거는 그려진 폭이 아니라 그 칸에 적힌 숫자다.
       */
      inline: showsInlineLabel(shownPercent),
      rating,
      label: toPercent(value),
    }
  })
}

/*
 * ── 반복 횟수 검증 (#1096 ⑴) ─────────────────────────────────────────────
 *
 * 서버 규칙은 `Field(ge=1_000)`(`api/schemas/annual_simulation.py`) — **정수 1,000
 * 이상**이면 받고, 10,000 초과는 상한으로 잘라 실행하며 `SIMULATION_RUNS_CLAMPED`를
 * 싣는다(`API_SPEC §6.1`). 화면은 하한·정수를 서버와 같게 막고, **상한도 막는다** —
 * 잘려서 실행되는 값을 받아 주면 사용자가 넣은 횟수와 돌아간 횟수가 다르고, 그 차이는
 * 경고 한 줄로만 드러난다. 힌트가 이미 「1,000~10,000회」라 적고 있다.
 *
 * 종전의 `step={1000}`은 이 규칙 어디에도 없는 제약이었다 — 2,500이 브라우저 기본
 * 툴팁으로만 막혔다.
 */
export const RUNS_MIN = 1_000
export const RUNS_MAX = 10_000

/**
 * 목표 등급 기본값 (`PRD §12.2` 입력 표 — 기본 **C**).
 *
 * 종전 화면은 **B**로 시작했다 (`#1453`). PRD 입력 표는 C인데 같은 문서의 요청 예시가
 * B라, 화면이 예시를 따랐다. 대부분의 사용자는 첫 값을 바꾸지 않고 실행하므로
 * 「B 이상 받을 확률」이 **사용자가 고른 적 없는 목표**로 나왔다.
 *
 * C는 규제 준수선이다. 제품이 기본값으로 「한 단계 더 잘하라」를 정해 두지 않는다 —
 * 목표를 올리는 것은 사용자의 몫이다(`§11` 중립). 표·예시·화면 세 곳이 이 값을 공유하며
 * `targetDefault.sync.test.ts`가 대조한다.
 */
export const TARGET_DEFAULT = 'C'

/** 반복 횟수 기본값 (`PRD §12.2` 기본 5,000). 화면 초깃값과 「바꿈」 판정이 같은 값을 본다. */
export const RUNS_DEFAULT = '5000'

/**
 * 고급 설정에서 기본값이 아닌 칸의 수 (#1418).
 *
 * 접힌 요약이 「기본값으로 실행」인지 「n개 바꿈」인지를 가른다. 보이지 않는 칸이 결과를 바꾸고
 * 있다면 접은 쪽이 그 사실을 말해야 한다. 공백만 있는 칸은 비운 것으로 본다 — 실행도 그렇게
 * 다룬다(`seed.trim()`).
 */
export function countAdvancedChanges(values: {
  runs: string
  seed: string
  applyFeedback: boolean
  alternativeFuel: string
}): number {
  return [
    values.runs.trim() !== RUNS_DEFAULT,
    values.seed.trim() !== '',
    values.applyFeedback,
    values.alternativeFuel !== '',
  ].filter(Boolean).length
}

/** 반복 횟수 입력의 위반. 없으면 `null`. 문구는 `copy.ts`가 갖는다. */
export function validateRuns(text: string): string | null {
  const trimmed = text.trim()
  if (!/^-?\d+$/.test(trimmed)) return ANNUAL_COPY.runsNotInteger
  const value = Number(trimmed)
  if (value < RUNS_MIN) return ANNUAL_COPY.runsBelowMin
  if (value > RUNS_MAX) return ANNUAL_COPY.runsAboveMax
  return null
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
 * ## 넘기는 값은 `shownPercent`다 (#846)
 *
 * `percent`(float)를 넘기면 **화면에 「8.0%」라고 쓰인 칸이 문자를 못 받는다** —
 * `'0.0795'`가 `7.949999…`이기 때문이다. 사용자가 읽는 근거는 그 칸에 적힌
 * 숫자이므로, 표시와 같은 반올림을 거친 값으로 판정한다.
 *
 * ## 합이 100%가 아니어도 정규화하지 않는다
 *
 * 판정은 **구간 자신의 값**만 본다. 서버 확률의 합이 반올림으로 99.9%나 100.1%가
 * 되는 일이 있는데, 그때 100%로 맞춰 늘렸다가는 화면에 쓰인 숫자와 판정 근거가
 * 또 어긋난다.
 */
// 이 파일 안에서만 쓴다 — `stackSegments`가 판정을 끝내므로 밖에서 부를 일이 없다 (#594).
function showsInlineLabel(percent: number): boolean {
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



/**
 * 「목표까지 줄여야 하는 양」의 두 값 (#1539).
 *
 * 서버는 CO₂를 **그램**(`required_cut_gco2` — CII 분자와 같은 단위)으로 준다. 종전에는 그대로
 * `2785954859 g`로 적었다 — 구분자도 환산도 없어 자릿수를 세어야 읽혔고, 다른 화면은 같은 양을
 * `2,710.6 tCO₂`로 적는다. 연료도 2자리(`894.65 t`)라 `§4.2` 1자리와 달랐다.
 *
 * **g → t는 소수점을 여섯 자리 옮긴다** — 나눗셈을 부동소수로 하지 않는다(`§4.1` 반올림은
 * 문자열로 한다). 옮긴 뒤 `§4.2` 자릿수 · 구분자 · 단위(`tCO₂` · `t`)로 적는다.
 */
export function reductionCutText(gco2: string, fuelTon: string): { co2: string; fuel: string } {
  return {
    co2: `${formatGrouped(gramsToTonnes(gco2), DISPLAY_DIGITS.co2Ton)} ${DISPLAY_UNITS.co2}`,
    fuel: `${formatGrouped(fuelTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`,
  }
}

/** 십진 문자열의 소수점을 왼쪽으로 여섯 자리 옮긴다 (g → t). */
function gramsToTonnes(grams: string): string {
  const trimmed = grams.trim()
  const negative = trimmed.startsWith('-')
  const unsigned = trimmed.replace(/^[+-]/, '')
  const [intPart, fracPart = ''] = unsigned.split('.')
  const padded = intPart.padStart(7, '0')
  const tonnes = `${padded.slice(0, -6)}.${padded.slice(-6)}${fracPart}`
  return negative ? `-${tonnes}` : tonnes
}

/**
 * 대상 선박을 화면에 적을 이름 (#1553).
 *
 * 이름은 셸이 이미 받은 목록(`shell.vessels`)에서 읽는다 — 새로 조회하지 않는다. 목록에서
 * 못 찾으면 **왜 못 찾았는지**를 가른다 — 아직 오는 중과 못 받은 것은 사용자가 할 일이 다르다.
 * 선박 id(UUID)를 대신 적지 않는다.
 */
export function targetVesselText(
  vesselId: string | null,
  vessels: readonly { id: string; displayName: string }[],
  vesselsState: 'loading' | 'ready' | 'failed',
  copy: { none: string; loading: string; unknown: string },
): string {
  if (vesselId === null) return copy.none
  const found = vessels.find((vessel) => vessel.id === vesselId)
  if (found) return found.displayName
  return vesselsState === 'loading' ? copy.loading : copy.unknown
}

/**
 * 결과 머리의 조건 한 줄 — 「샘플 벌크선 · 2026년 · 목표 등급 C」 (#1553).
 *
 * **실행 시점의 값**을 받는다. 배 · 연도를 바꾸면 결과가 지워지지만(`#1094`) 목표 등급은
 * 지우지 않으므로(같은 조건으로 두 배를 비교하려고) 지금 고른 값을 적으면 결과와 어긋난다.
 */
export function resultConditionsText(conditions: {
  vesselName: string
  year: string
  target: string
}): string {
  return `${conditions.vesselName} · ${conditions.year}년 · 목표 등급 ${conditions.target}`
}

/**
 * 결과 위 화면 단위 추정 고지 (`DESIGN_SYSTEM §11` · #1578).
 *
 * §11은 전면 추정 화면이 개별 표기를 고지로 갈음할 때 **추정 성격과 기준 시각**을 담으라고
 * 한다. 기준 시각은 응답 `meta.as_of` — 집계에 실제로 쓴 시각이다. 없으면 추정 성격만
 * 말한다(빈 시각을 지어내지 않는다).
 */
export function estimateNoticeText(asOf: string | undefined): string {
  if (asOf === undefined) return ANNUAL_COPY.estimateNotice
  const time = formatTimestamp(asOf)
  return `${ANNUAL_COPY.estimateNotice} ${ANNUAL_COPY.estimateAsOf.replace('{time}', time)}`
}
