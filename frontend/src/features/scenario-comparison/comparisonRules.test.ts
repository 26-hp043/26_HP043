import { describe, expect, it } from 'vitest'
import {
  compareDecimalStrings,
  deltaFromDirect,
  isZeroDelta,
  lowestScenario,
  lowestSummary,
  subtractFixed,
} from './comparisonRules'
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

describe('직항 대비 차이 (#739)', () => {
  /* 화면에서 실제로 나온 값이다 — 샘플 벌크선 50,000 DWT · 1,000 nm · 12.8 kn. */
  const DIRECT: ScenarioResult = {
    ...scenario('DIRECT', { cii: '6.6144', hours: '78.125', fuel: '106.187' }),
    scenario_name: '직항',
    distance_nm: 1000,
    speed_kn: 12.8,
    co2_emission_ton: '330.665',
  }
  const DETOUR: ScenarioResult = {
    ...scenario('DETOUR', { cii: '6.6144', hours: '82.031', fuel: '111.501' }),
    scenario_name: '우회',
    distance_nm: 1050,
    speed_kn: 12.8,
    co2_emission_ton: '347.215',
  }

  it('표시 자릿수에서 뺀다 — 화면의 두 값을 눈으로 빼면 맞아야 한다', () => {
    const delta = deltaFromDirect(DETOUR, DIRECT)!
    // 화면에는 106.2 t와 111.5 t가 뜬다. 원본으로 빼면 5.314 → 5.3으로 같지만,
    // 반올림이 서로 다른 쪽으로 가는 조합에서는 두 값이 갈린다 — 아래 단언이 그 경우다.
    expect(delta.fuelTon).toBe('5.3')
    expect(delta.co2Ton).toBe('16.5')
    expect(delta.distanceNm).toBe('50')
    expect(delta.durationHours).toBe('3.9')
  })

  it('원본이 아니라 표시값을 뺀다 — 반올림이 갈리는 자리에서 드러난다', () => {
    /*
     * 0.04와 0.05는 원본으로 빼면 0.01(1자리 표시로는 0.0)이지만, 화면에는
     * `0.0`과 `0.1`이 뜬다. 그 두 값을 눈으로 빼면 -0.1이고, 화면이 -0.0이라
     * 적으면 **화면 안에서 셋 중 하나가 틀린 것으로 보인다.**
     */
    expect(subtractFixed('0.04', '0.05', 1)).toBe('-0.1')
  })

  it('우회는 CII를 바꾸지 않는다 — 거리당 값이기 때문이다', () => {
    /*
     * 같은 속력이면 연료가 시간에, 시간이 거리에 비례해 분자와 분모가 같은 비율로
     * 늘어난다. 이 단언이 화면의 「직항과 같습니다」 문구가 서는 자리를 잠근다.
     */
    const delta = deltaFromDirect(DETOUR, DIRECT)!
    expect(delta.cii).toBe('0.000')
    expect(isZeroDelta(delta.cii)).toBe(true)
  })

  it('음수도 부호를 유지한다', () => {
    const slow: ScenarioResult = {
      ...DIRECT,
      scenario_type: 'SLOW_STEAMING',
      fuel_ton: '90.31',
      attained_cii: '5.6213',
    }

    const delta = deltaFromDirect(slow, DIRECT)!
    expect(delta.fuelTon).toBe('-15.9')
    expect(delta.cii).toBe('-0.993')
    expect(isZeroDelta(delta.fuelTon)).toBe(false)
  })

  it('기준 시나리오 자신에게는 차이가 없다', () => {
    // 0으로 채우면 기준 카드에 아무것도 말하지 않는 「직항 대비 0」 줄이 생긴다.
    expect(deltaFromDirect(DIRECT, DIRECT)).toBeNull()
    expect(deltaFromDirect(DETOUR, undefined)).toBeNull()
  })

  it('subtractFixed는 자릿수를 지킨다', () => {
    expect(subtractFixed('1.005', '1.000', 3)).toBe('0.005')
    expect(subtractFixed('1', '2', 0)).toBe('-1')
    // 자리올림이 정수부를 넘어가도 BigInt라 흔들리지 않는다.
    expect(subtractFixed('1000000000000000000.1', '0.2', 1)).toBe('999999999999999999.9')
  })

  it('isZeroDelta는 부호와 자릿수에 흔들리지 않는다', () => {
    expect(isZeroDelta('0')).toBe(true)
    expect(isZeroDelta('0.000')).toBe(true)
    expect(isZeroDelta('-0.0')).toBe(true)
    expect(isZeroDelta('0.001')).toBe(false)
  })
})
