import { DISPLAY_DIGITS, formatDecimalString, formatTimestamp } from '../../display/format'
import { signedPercent } from './requestRules'
import type { ScenarioConditions, ScenarioResult, ScenarioType, UnreachableScenario } from './types'

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

/**
 * 지표별 최소값을 고를 때 볼 값.
 *
 * `hours_to_berth`는 **접안까지 시간**이다 (#2561 결정 D8). 선석 시각을 넣으면 「가장 짧음」을
 * 항해 시간이 아니라 이것으로 견준다 — 선석보다 먼저 닿아 기다리는 직항이 「가장 짧음」을
 * 받으면 그 전에는 접안할 수 없다는 사실과 어긋난다. 서버 `summary`와 같은 규칙이다.
 */
export type ComparableMetric = 'attained_cii' | 'duration_hours' | 'fuel_ton' | 'hours_to_berth'

/** 한 시나리오에서 그 지표의 값. 선석 대기가 없으면 접안까지 = 항해 시간이다. */
export function metricValue(scenario: ScenarioResult, metric: ComparableMetric): string {
  if (metric === 'hours_to_berth') return scenario.berth?.hours_to_berth ?? scenario.duration_hours
  return scenario[metric]
}

/**
 * 선석 시각을 넣은 비교인가 — 시나리오에 선석 대기가 실려 있다 (#2561). 키가 없는 것(옛 응답 ·
 * 가짜 provider)도 「없음」으로 읽는다.
 */
export function hasBerth(scenarios: readonly ScenarioResult[]): boolean {
  return scenarios.some((s) => (s.berth ?? null) !== null)
}

/**
 * 지표별 최소값 시나리오 — `PRD §11.2`.
 *
 * > 시스템은 `추천 시나리오`를 표시하지 않는다. 대신 각 지표별 최소값을
 * > **중립적으로** 표시한다.
 *
 * 종합 점수를 매기거나 하나를 고르지 않는다. **지표마다 따로** 최소값을 낸다 —
 * 어느 지표가 중요한지는 사용자가 정한다(`PRD §6.3` 「자동 결정 금지」).
 *
 * **동률이면 전부 돌려준다** (`#799` · 아래 본문 주석). 같은 값 중 하나만 지목하는
 * 것은 그 자체가 추천이기 때문이다 — 종전 이 자리는 「먼저 나온 시나리오를 고른다」로
 * 적혀 **본문과 반대**를 말하고 있었다(`#1619` 정정).
 */
export function lowestScenarios(
  scenarios: readonly ScenarioResult[],
  metric: ComparableMetric,
): ScenarioType[] {
  if (scenarios.length === 0) return []

  /*
   * **동률이면 전부 돌려준다** (`PRD §11.2`, `#799`).
   *
   * 종전에는 하나만 골랐다. **같은 값 중 하나만 지목하는 것은 그 자체가 추천**이고,
   * 같은 절의 「추천 시나리오를 표시하지 않는다」에 어긋난다 — 사용자는 두 시나리오의
   * CII가 화면에 같게 찍혀 있는데 한쪽만 「가장 낮은」으로 불리는 것을 보고 그쪽이
   * 낫다고 읽는다.
   *
   * 동률은 드문 일이 아니라 **정의상 필연**인 경우가 있다: `PRD §11.4.1` cubic speed
   * model에서 연료는 거리에 비례하고 AER은 거리로 나누므로, **같은 속도의 직항과
   * 우회는 `attained_cii`가 정확히 같다.**
   */
  let best = metricValue(scenarios[0], metric)
  for (const candidate of scenarios.slice(1)) {
    const value = metricValue(candidate, metric)
    if (compareDecimalStrings(value, best) < 0) best = value
  }
  return scenarios
    .filter((s) => compareDecimalStrings(metricValue(s, metric), best) === 0)
    .map((s) => s.scenario_type)
}

/** 화면에 그대로 쓰는 「가장 낮은 시나리오」 3줄. `PRD §11.2` 예시 문구 형식이다. */
export interface LowestSummary {
  metric: ComparableMetric
  label: string
  /** 동률이면 여럿이다 (`PRD §11.2`, `#799`). 결과가 없으면 빈 배열이다. */
  scenarioTypes: ScenarioType[]
}

export function lowestSummary(scenarios: readonly ScenarioResult[]): LowestSummary[] {
  const duration: LowestSummary = hasBerth(scenarios)
    ? { metric: 'hours_to_berth', label: '접안까지 시간이 가장 짧은 시나리오', scenarioTypes: lowestScenarios(scenarios, 'hours_to_berth') }
    : { metric: 'duration_hours', label: '소요시간이 가장 짧은 시나리오', scenarioTypes: lowestScenarios(scenarios, 'duration_hours') }
  return [
    { metric: 'attained_cii', label: 'CII가 가장 낮은 시나리오', scenarioTypes: lowestScenarios(scenarios, 'attained_cii') },
    duration,
    { metric: 'fuel_ton', label: '연료 사용량이 가장 낮은 시나리오', scenarioTypes: lowestScenarios(scenarios, 'fuel_ton') },
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
 * 원본이 아니라 표시 자릿수로 맞춘 문자열을 정수로 올려 뺀다(`display/decimal.ts`).
 * 사용자는 화면의 두 값을 눈으로 빼 보고 차이와 맞는지 확인한다. 원본을 빼면
 * `106.2` · `111.5` 옆에 `+5.4`가 붙는 일이 생긴다 — 숨은 자리 때문에 맞는 값인데,
 * **화면만 보는 사람에게는 셋 중 하나가 틀린 것으로 보인다.**
 */

/*
 * 십진 사칙은 `display/decimal.ts`로 옮겼다 (`#820`). 연간 시뮬레이션 화면이 같은
 * 계산을 필요로 했고, **복사하면 한쪽만 고쳐질 수 있다** — `#820`이 고치는 결함이
 * 정확히 그 모양이다. 이 모듈의 공개 이름(`subtractFixed`)은 그대로 둔다.
 */
import { subtractFixed } from '../../display/decimal'

export { subtractFixed }

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

/**
 * 결과 머리의 조건 한 줄 — 선체·추진 상태 보정 (#2561).
 *
 * **세 출처를 다른 말로 적는다.** 미입력과 0%는 계산이 같지만 앞은 「모른다」이고 뒤는
 * 「깨끗하다고 확인했다」다 — 같게 그리면 사용자는 보정이 걸리지 않은 결과를 「보정 0%로
 * 확인된 결과」로 읽는다. 조건을 받지 못한 응답(가짜 provider·옛 응답)은 `null`이라 줄을
 * 내지 않는다 — 출처를 지어 적지 않는다.
 */
export function hullConditionText(conditions: ScenarioConditions | null | undefined): string | null {
  if (conditions === null || conditions === undefined) return null
  const percent = conditions.hull_condition_percent
  if (conditions.hull_condition_source === 'NOT_SET' || percent === null) {
    return '선체 상태 보정: 미입력 — 0%로 계산했습니다.'
  }
  const origin =
    conditions.hull_condition_source === 'REQUEST' ? '이번 비교에서 입력한 값' : '선박 제원값'
  return `선체 상태 보정: ${signedPercent(percent)} (${origin}) — 세 시나리오의 연료에 같은 비율로 반영했습니다.`
}

/**
 * 결과 머리의 선석 조건 한 줄 (#2561 결정 D1·D3). 선석 시각을 넣지 않은 비교면 `null`이다.
 *
 * 묘박 연료의 **출처 셋을 다른 말로** 적는다 — 선체 상태 줄(`hullConditionText`)과 같은 이유다.
 * 미입력이면 대기 연료·대기 포함 CII를 **내지 않았다**고 밝힌다. 0으로 계산한 것이 아니다.
 */
export function berthConditionText(conditions: ScenarioConditions | null | undefined): string | null {
  if (conditions === null || conditions === undefined) return null
  const at = conditions.berth_available_at
  const hours = conditions.hours_until_berth
  if (at === null || at === undefined || hours === null || hours === undefined) return null
  const when = formatTimestamp(at) ?? at
  const until = formatDecimalString(hours, DISPLAY_DIGITS.durationHours)
  const lead = `선석 가용 시각: ${when} (${until}시간 뒤)`
  const foc = conditions.anchorage_daily_foc_ton
  if (conditions.anchorage_daily_foc_source === 'NOT_SET' || foc === null) {
    return `${lead} — 묘박 중 일일 연료가 미입력이라 대기 연료와 대기 포함 CII는 계산하지 않았습니다.`
  }
  const origin =
    conditions.anchorage_daily_foc_source === 'REQUEST' ? '이번 비교에서 입력한 값' : '선박 제원값'
  const focText = foc.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
  return `${lead} · 묘박 중 일일 연료 ${focText}t/일 (${origin})`
}

/**
 * 채택 칸의 대기 고지 (`PRD §6.3` 「시나리오 채택 — 선석 대기가 있는 시나리오」 · 결정 D4).
 *
 * 대기가 없으면 `null`이다 — 붙이지 않는다. 묘박 연료를 몰라 대기 연료가 없으면 시간만 말한다.
 */
export function berthAdoptNotice(scenario: ScenarioResult): string | null {
  const berth = scenario.berth ?? null
  if (berth === null || isZeroDelta(berth.waiting_hours)) return null
  const hours = formatDecimalString(berth.waiting_hours, DISPLAY_DIGITS.durationHours)
  if (berth.waiting_fuel_ton === null) {
    // 정본 문구 (PRD §6.3) — 바꾸려면 PRD 개정이 먼저다.
    return `선석 대기 ${hours}시간은 항차 계획에 담기지 않습니다.`
  }
  const fuel = formatDecimalString(berth.waiting_fuel_ton, DISPLAY_DIGITS.fuelTon)
  // 정본 문구 (PRD §6.3) — 바꾸려면 PRD 개정이 먼저다.
  return `선석 대기 ${hours}시간(대기 연료 ${fuel}t)은 항차 계획에 담기지 않습니다.`
}

/**
 * 도달 불가 한 줄 (#2561). 맞춤 속도가 상한(60kn)을 넘어 계산하지 않은 시나리오다.
 */
export function unreachableText(item: UnreachableScenario): string {
  const speed = item.required_speed_kn.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
  return `${item.scenario_name}: 도달 불가 — 선석 가용 시각에 맞추려면 ${speed}kn가 필요해 계산하지 않았습니다(최대 60kn).`
}

/**
 * 경고 코드 → 그 경고가 붙은 시나리오 이름들 (#2561 · `scenarios[].warnings`). 귀속이 없는 경고
 * (화면 전체의 것)는 맵에 없다.
 */
export function scenarioWarningOwners(scenarios: readonly ScenarioResult[]): Record<string, string> {
  const owners: Record<string, string[]> = {}
  for (const scenario of scenarios) {
    for (const code of scenario.warnings ?? []) {
      ;(owners[code] ??= []).push(scenario.scenario_name)
    }
  }
  return Object.fromEntries(Object.entries(owners).map(([code, names]) => [code, names.join(' · ')]))
}
