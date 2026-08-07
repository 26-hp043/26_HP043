import { describe, expect, it } from 'vitest'
import { compareDecimalStrings, lowestScenario, lowestSummary } from './comparisonRules'
import type { ScenarioResult, ScenarioType } from './types'

function scenario(
  type: ScenarioType,
  values: { cii: string; hours: string; fuel: string },
): ScenarioResult {
  return {
    scenario_type: type,
    scenario_name: type,
    distance_nm: 1000,
    speed_kn: 14,
    duration_hours: values.hours,
    fuel_ton: values.fuel,
    co2_emission_ton: '249.12',
    attained_cii: values.cii,
    ratio_to_required: '0.98758',
    estimated_rating: 'C',
    risk_level: 'MEDIUM',
    next_worse_boundary_margin_ratio: '0.0724',
  }
}

describe('compareDecimalStrings — Number를 거치지 않는다', () => {
  it.each([
    ['1', '2', -1],
    ['2', '1', 1],
    ['1', '1', 0],
    ['1.0', '1', 0],
    ['1.10', '1.1', 0],
    ['9', '10', -1],
    ['10', '9', 1],
    ['0.9', '0.10', 1],
    ['4.982400', '5.219657', -1],
    ['-1', '1', -1],
    ['-2', '-1', -1],
    ['-0', '0', 0],
  ])('%s vs %s → %s', (a, b, expected) => {
    expect(Math.sign(compareDecimalStrings(a, b))).toBe(expected)
  })

  it('앞자리 0이 대소를 바꾸지 않는다', () => {
    expect(compareDecimalStrings('007', '7')).toBe(0)
    expect(compareDecimalStrings('0007', '10')).toBeLessThan(0)
  })

  it('배정밀도로는 구분되지 않는 자리에서도 갈린다', () => {
    // Number로 바꾸면 둘 다 같은 값이 된다.
    const a = '1.0000000000000000000000000001'
    const b = '1.0000000000000000000000000002'
    expect(Number(a) === Number(b)).toBe(true)
    expect(compareDecimalStrings(a, b)).toBeLessThan(0)
  })

  it('정수부 자릿수가 다르면 사전순에 속지 않는다', () => {
    // 문자열 사전순이면 '9' > '10' 이라 틀린다.
    expect(compareDecimalStrings('9.5', '10.1')).toBeLessThan(0)
  })
})

describe('lowestScenario — PRD §11.2', () => {
  const scenarios = [
    scenario('DIRECT', { cii: '4.982400', hours: '71.4286', fuel: '80.00' }),
    scenario('DETOUR', { cii: '5.219657', hours: '75.0000', fuel: '88.00' }),
    scenario('SLOW_STEAMING', { cii: '4.297320', hours: '76.9231', fuel: '69.00' }),
  ]

  it('CII가 가장 낮은 시나리오', () => {
    expect(lowestScenario(scenarios, 'attained_cii')).toBe('SLOW_STEAMING')
  })

  it('소요시간이 가장 짧은 시나리오', () => {
    expect(lowestScenario(scenarios, 'duration_hours')).toBe('DIRECT')
  })

  it('연료 사용량이 가장 낮은 시나리오', () => {
    expect(lowestScenario(scenarios, 'fuel_ton')).toBe('SLOW_STEAMING')
  })

  it('지표마다 답이 다를 수 있다 — 하나를 추천하지 않는다', () => {
    // PRD §11.2: 「시스템은 추천 시나리오를 표시하지 않는다」
    const picked = new Set(
      (['attained_cii', 'duration_hours', 'fuel_ton'] as const).map((m) =>
        lowestScenario(scenarios, m),
      ),
    )
    expect(picked.size).toBeGreaterThan(1)
  })

  it('동률이면 앞선 시나리오를 고른다 — 결과가 흔들리지 않는다', () => {
    const tied = [
      scenario('DIRECT', { cii: '5.0', hours: '10', fuel: '50' }),
      scenario('DETOUR', { cii: '5.00', hours: '10', fuel: '50' }),
    ]
    expect(lowestScenario(tied, 'attained_cii')).toBe('DIRECT')
    expect(lowestScenario(tied, 'fuel_ton')).toBe('DIRECT')
  })

  it('빈 배열은 null', () => {
    expect(lowestScenario([], 'attained_cii')).toBeNull()
  })
})

describe('lowestSummary', () => {
  it('PRD §11.2 예시의 세 줄을 그대로 낸다', () => {
    const summary = lowestSummary([
      scenario('DIRECT', { cii: '4.982400', hours: '71.4286', fuel: '80.00' }),
      scenario('DETOUR', { cii: '5.219657', hours: '75.0000', fuel: '88.00' }),
      scenario('SLOW_STEAMING', { cii: '4.297320', hours: '76.9231', fuel: '69.00' }),
    ])
    expect(summary.map((s) => `${s.label}: ${s.scenarioType}`)).toEqual([
      'CII가 가장 낮은 시나리오: SLOW_STEAMING',
      '소요시간이 가장 짧은 시나리오: DIRECT',
      '연료 사용량이 가장 낮은 시나리오: SLOW_STEAMING',
    ])
  })
})
