import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import type { ScenarioResult, ScenarioType } from './types'

/**
 * 기능② 비교 표시 규칙 (#156).
 *
 * ⚠️ **Layer 1 값에 `parseFloat`·`Number`를 쓰지 않는다**(`API_SPEC §1.7`
 * `[ORACLE-C-1]`). 최소값을 고르는 비교도 문자열로 한다.
 */

/**
 * 십진 문자열 두 개를 비교한다. `a < b`면 음수, 같으면 0, 크면 양수.
 *
 * **`Number`를 거치지 않는다.** 정수부 길이를 먼저 보고, 같으면 자릿수를 맞춘 뒤
 * 사전순으로 비교한다 — 소수부를 0으로 패딩하면 사전순이 곧 수의 대소가 된다.
 */
export function compareDecimalStrings(a: string, b: string): number {
  const pa = parseSign(a)
  const pb = parseSign(b)
  if (pa.negative !== pb.negative) return pa.negative ? -1 : 1

  const magnitude = compareMagnitude(pa, pb)
  return pa.negative ? -magnitude : magnitude
}

interface Parsed {
  negative: boolean
  int: string
  frac: string
}

function parseSign(value: string): Parsed {
  const trimmed = value.trim()
  const negative = trimmed.startsWith('-')
  const unsigned = trimmed.replace(/^[+-]/, '')
  const [rawInt = '0', frac = ''] = unsigned.split('.')
  const int = rawInt.replace(/^0+(?=\d)/, '')
  // -0 은 0과 같다
  return { negative: negative && /[1-9]/.test(unsigned), int, frac }
}

function compareMagnitude(a: Parsed, b: Parsed): number {
  if (a.int.length !== b.int.length) return a.int.length < b.int.length ? -1 : 1
  if (a.int !== b.int) return a.int < b.int ? -1 : 1

  const width = Math.max(a.frac.length, b.frac.length)
  const fa = a.frac.padEnd(width, '0')
  const fb = b.frac.padEnd(width, '0')
  if (fa === fb) return 0
  return fa < fb ? -1 : 1
}

/** 지표별 최소값을 고를 때 볼 필드. */
export type ComparableMetric = 'attained_cii' | 'duration_hours' | 'fuel_ton'

/**
 * 지표별 최소값 시나리오 — `PRD §11.2`.
 *
 * > 시스템은 `추천 시나리오`를 표시하지 않는다. 대신 각 지표별 최소값을
 * > **중립적으로** 표시한다.
 *
 * 종합 점수를 매기거나 하나를 고르지 않는다. **지표마다 따로** 최소값을 낸다 —
 * 어느 지표가 중요한지는 사용자가 정한다(`PRD §6.3` 「자동 결정 금지」).
 *
 * 동률이면 **먼저 나온 시나리오**를 고른다. `PRD §11.2` 표 순서가 곧 배열 순서라
 * 결과가 흔들리지 않는다.
 */
export function lowestScenario(
  scenarios: readonly ScenarioResult[],
  metric: ComparableMetric,
): ScenarioType | null {
  if (scenarios.length === 0) return null

  let best = scenarios[0]
  for (const candidate of scenarios.slice(1)) {
    if (compareDecimalStrings(candidate[metric], best[metric]) < 0) {
      best = candidate
    }
  }
  return best.scenario_type
}

/** 화면에 그대로 쓰는 「가장 낮은 시나리오」 3줄. `PRD §11.2` 예시 문구 형식이다. */
export interface LowestSummary {
  metric: ComparableMetric
  label: string
  scenarioType: ScenarioType | null
}

export function lowestSummary(scenarios: readonly ScenarioResult[]): LowestSummary[] {
  return [
    { metric: 'attained_cii', label: 'CII가 가장 낮은 시나리오', scenarioType: lowestScenario(scenarios, 'attained_cii') },
    { metric: 'duration_hours', label: '소요시간이 가장 짧은 시나리오', scenarioType: lowestScenario(scenarios, 'duration_hours') },
    { metric: 'fuel_ton', label: '연료 사용량이 가장 낮은 시나리오', scenarioType: lowestScenario(scenarios, 'fuel_ton') },
  ]
}

/* ------------------------------------------------------------------ */

/**
 * 직항 대비 차이 — `#739`.
 *
 * 세 시나리오를 나란히 놓기만 하고 **차이는 사용자가 머릿속에서 빼고 있었다.**
 * 비교하러 온 화면이므로 그 뺄셈을 화면이 한다.
 *
 * ## `Number`를 쓰지 않는다 — `BigInt`다
 *
 * 이 모듈은 헤더대로 `parseFloat`·`Number`를 쓰지 않는다(`API_SPEC §1.7`
 * `[ORACLE-C-1]`). `BigInt`는 정밀도를 잃지 않으므로 그 금지에 걸리지 않는다 —
 * 막는 것은 `Decimal` 30자리를 float 53비트로 눌러 담는 일이지 정수 연산이 아니다.
 *
 * ## **표시값**을 뺀다
 *
 * 원본이 아니라 `formatDecimalString`이 낸 고정 자릿수 문자열을 정수로 올려 뺀다.
 * 사용자는 화면의 두 값을 눈으로 빼 보고 차이와 맞는지 확인한다. 원본을 빼면
 * `106.2` · `111.5` 옆에 `+5.4`가 붙는 일이 생긴다 — 숨은 자리 때문에 맞는 값인데,
 * **화면만 보는 사람에게는 셋 중 하나가 틀린 것으로 보인다.**
 */

/** 고정 자릿수 십진 문자열을 그 자릿수만큼 올린 정수로. `'106.2'`·1 → `1062n` */
function displayScaled(value: string, digits: number): bigint {
  const fixed = formatDecimalString(value, digits)
  const negative = fixed.startsWith('-')
  const magnitude = BigInt(fixed.replace(/[^0-9]/g, ''))
  return negative ? -magnitude : magnitude
}

/** 올린 정수를 다시 십진 문자열로. `53n`·1 → `'5.3'` */
function unscale(scaled: bigint, digits: number): string {
  const negative = scaled < 0n
  const absolute = (negative ? -scaled : scaled).toString().padStart(digits + 1, '0')
  const cut = absolute.length - digits
  const body = digits === 0 ? absolute : `${absolute.slice(0, cut)}.${absolute.slice(cut)}`
  return negative ? `-${body}` : body
}

/** 표시 자릿수에서의 `a - b`. 부호를 포함한 십진 문자열이다. */
export function subtractFixed(a: string, b: string, digits: number): string {
  return unscale(displayScaled(a, digits) - displayScaled(b, digits), digits)
}

/** 직항 대비 차이 한 벌. 전부 부호를 포함한 십진 문자열이다. */
export interface ScenarioDelta {
  cii: string
  distanceNm: string
  durationHours: string
  fuelTon: string
  co2Ton: string
}

/**
 * `scenario`가 `direct`보다 얼마나 많은가/적은가.
 *
 * 기준 시나리오 자신에게는 차이가 없으므로 `null`이다 — `0`을 채우면 「직항 대비
 * 0」이라는 빈 줄이 기준 카드에 생기고, 그 줄은 아무것도 말하지 않는다.
 */
export function deltaFromDirect(
  scenario: ScenarioResult,
  direct: ScenarioResult | undefined,
): ScenarioDelta | null {
  if (direct === undefined || scenario.scenario_type === direct.scenario_type) return null

  return {
    cii: subtractFixed(scenario.attained_cii, direct.attained_cii, DISPLAY_DIGITS.cii),
    distanceNm: subtractFixed(
      String(scenario.distance_nm),
      String(direct.distance_nm),
      DISPLAY_DIGITS.distanceNm,
    ),
    durationHours: subtractFixed(
      scenario.duration_hours,
      direct.duration_hours,
      DISPLAY_DIGITS.durationHours,
    ),
    fuelTon: subtractFixed(scenario.fuel_ton, direct.fuel_ton, DISPLAY_DIGITS.fuelTon),
    co2Ton: subtractFixed(
      scenario.co2_emission_ton,
      direct.co2_emission_ton,
      DISPLAY_DIGITS.co2Ton,
    ),
  }
}

/** 부호 없는 0인가 — `'0'` · `'0.0'` · `'-0.000'` 모두 참이다. */
export function isZeroDelta(value: string): boolean {
  return !/[1-9]/.test(value)
}
