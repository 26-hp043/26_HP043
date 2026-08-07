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
