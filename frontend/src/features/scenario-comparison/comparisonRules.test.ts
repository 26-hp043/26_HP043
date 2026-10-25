import { describe, expect, it } from 'vitest'
import {
  compareDecimalStrings,
  deltaFromDirect,
  isZeroDelta,
  lowestScenarios,
  lowestSummary,
  subtractFixed,
  hullConditionText,
  berthAdoptNotice,
  berthConditionText,
  hasBerth,
  metricValue,
  scenarioWarningOwners,
  unreachableText,
} from './comparisonRules'
import type { ScenarioResult, ScenarioType } from './types'

function scenario(
  type: ScenarioType,
  values: { cii: string; hours: string; fuel: string },
): ScenarioResult {
  return {
    scenario_id: `id-${type}`,
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
    warnings: [],
    berth: null,
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

describe('lowestScenarios — PRD §11.2', () => {
  const scenarios = [
    scenario('DIRECT', { cii: '4.982400', hours: '71.4286', fuel: '80.00' }),
    scenario('DETOUR', { cii: '5.219657', hours: '75.0000', fuel: '88.00' }),
    scenario('SLOW_STEAMING', { cii: '4.297320', hours: '76.9231', fuel: '69.00' }),
  ]

  it('CII가 가장 낮은 시나리오', () => {
    expect(lowestScenarios(scenarios, 'attained_cii')).toEqual(['SLOW_STEAMING'])
  })

  it('소요시간이 가장 짧은 시나리오', () => {
    expect(lowestScenarios(scenarios, 'duration_hours')).toEqual(['DIRECT'])
  })

  it('연료 사용량이 가장 낮은 시나리오', () => {
    expect(lowestScenarios(scenarios, 'fuel_ton')).toEqual(['SLOW_STEAMING'])
  })

  it('지표마다 답이 다를 수 있다 — 하나를 추천하지 않는다', () => {
    // PRD §11.2: 「시스템은 추천 시나리오를 표시하지 않는다」
    const picked = new Set(
      (['attained_cii', 'duration_hours', 'fuel_ton'] as const).map((m) =>
        lowestScenarios(scenarios, m).join(','),
      ),
    )
    expect(picked.size).toBeGreaterThan(1)
  })

  it('동률이면 전부 돌려준다 — 하나만 지목하면 그것이 추천이다 (#799)', () => {
    // `PRD §11.4.1` cubic speed model에서 연료는 거리에 비례하고 AER은 거리로
    // 나누므로, **같은 속도의 직항과 우회는 CII가 정확히 같다.** 종전에는 앞선
    // 시나리오 하나만 골라 「직항이 CII가 가장 낮다」로 읽혔다.
    const tied = [
      scenario('DIRECT', { cii: '4.982400', hours: '10', fuel: '50' }),
      scenario('DETOUR', { cii: '4.982400', hours: '11', fuel: '52' }),
      scenario('SLOW_STEAMING', { cii: '4.297320', hours: '12', fuel: '45' }),
    ]

    expect(lowestScenarios(tied, 'attained_cii')).toEqual(['SLOW_STEAMING'])
    // 감속을 빼면 직항·우회가 동률이다.
    expect(lowestScenarios(tied.slice(0, 2), 'attained_cii')).toEqual(['DIRECT', 'DETOUR'])
  })

  it('표기가 달라도 값이 같으면 동률이다 — 5.0과 5.00', () => {
    // 문자열 비교가 아니라 십진 비교임을 고정한다.
    const tied = [
      scenario('DIRECT', { cii: '5.0', hours: '10', fuel: '50' }),
      scenario('DETOUR', { cii: '5.00', hours: '10', fuel: '50.0' }),
    ]
    expect(lowestScenarios(tied, 'attained_cii')).toEqual(['DIRECT', 'DETOUR'])
    expect(lowestScenarios(tied, 'fuel_ton')).toEqual(['DIRECT', 'DETOUR'])
  })

  it('빈 배열은 빈 배열', () => {
    expect(lowestScenarios([], 'attained_cii')).toEqual([])
  })
})

describe('lowestSummary', () => {
  it('PRD §11.2 예시의 세 줄을 그대로 낸다', () => {
    const summary = lowestSummary([
      scenario('DIRECT', { cii: '4.982400', hours: '71.4286', fuel: '80.00' }),
      scenario('DETOUR', { cii: '5.219657', hours: '75.0000', fuel: '88.00' }),
      scenario('SLOW_STEAMING', { cii: '4.297320', hours: '76.9231', fuel: '69.00' }),
    ])
    expect(summary.map((s) => `${s.label}: ${s.scenarioTypes.join(' · ')}`)).toEqual([
      'CII가 가장 낮은 시나리오: SLOW_STEAMING',
      '소요시간이 가장 짧은 시나리오: DIRECT',
      '연료 사용량이 가장 낮은 시나리오: SLOW_STEAMING',
    ])
  })

  it('동률이면 세 줄 중 해당 줄에 둘이 실린다 (#799)', () => {
    const summary = lowestSummary([
      scenario('DIRECT', { cii: '4.982400', hours: '71.4286', fuel: '80.00' }),
      scenario('DETOUR', { cii: '4.982400', hours: '75.0000', fuel: '84.00' }),
    ])

    expect(summary[0].scenarioTypes).toEqual(['DIRECT', 'DETOUR'])
    // 나머지 축은 실제로 갈린다 — 우회의 대가가 드러나는 자리다.
    expect(summary[1].scenarioTypes).toEqual(['DIRECT'])
    expect(summary[2].scenarioTypes).toEqual(['DIRECT'])
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

/** 선석 시각을 넣지 않은 비교의 조건 칸 (#2561 ②③). */
const NO_BERTH = {
  berth_available_at: null,
  hours_until_berth: null,
  anchorage_daily_foc_ton: null,
  anchorage_daily_foc_source: 'NOT_SET',
} as const

describe('선체 상태 보정 조건 줄 (#2561)', () => {
  it('세 출처를 서로 다른 말로 적는다 — 미입력과 0%를 같게 그리지 않는다', () => {
    const notSet = hullConditionText({ hull_condition_percent: null, hull_condition_source: 'NOT_SET', ...NO_BERTH })
    const zero = hullConditionText({ hull_condition_percent: 0, hull_condition_source: 'VESSEL', ...NO_BERTH })
    const request = hullConditionText({ hull_condition_percent: 20, hull_condition_source: 'REQUEST', ...NO_BERTH })
    const vessel = hullConditionText({ hull_condition_percent: 20, hull_condition_source: 'VESSEL', ...NO_BERTH })
    expect(new Set([notSet, zero, request, vessel]).size).toBe(4)
    expect(request).toContain('+20%')
    expect(vessel).toContain('+20%')
  })

  it('조건을 받지 못한 응답은 줄을 내지 않는다 — 출처를 지어 적지 않는다', () => {
    expect(hullConditionText(undefined)).toBeNull()
    expect(hullConditionText(null)).toBeNull()
  })
})

describe('선석 대기 — 판정·문구 (#2561 ②③)', () => {
  const waiting = (hours: string, toBerth: string, late = '0.0000', fuel: string | null = '1.07') => ({
    hours_to_berth: toBerth,
    waiting_hours: hours,
    late_hours: late,
    waiting_fuel_ton: fuel,
    attained_cii_with_waiting: fuel === null ? null : '5.627442',
    estimated_rating_with_waiting: fuel === null ? null : ('D' as const),
  })
  const withBerth = (base: ScenarioResult, berth: ScenarioResult['berth']): ScenarioResult => ({
    ...base,
    berth,
  })

  it('선석이 있으면 「가장 짧음」은 접안까지로 견준다 — 항해 시간이 짧아도 기다리면 동률이다', () => {
    const direct = withBerth(scenario('DIRECT', { cii: '5.56', hours: '71.4285', fuel: '89.28' }), waiting('8.5714', '80.0000'))
    const jit = withBerth(scenario('DIRECT_JIT', { cii: '4.43', hours: '80.0000', fuel: '71.17' }), waiting('0.0000', '80.0000'))
    expect(hasBerth([direct, jit])).toBe(true)
    expect(lowestScenarios([direct, jit], 'duration_hours')).toEqual(['DIRECT'])
    expect(lowestScenarios([direct, jit], 'hours_to_berth')).toEqual(['DIRECT', 'DIRECT_JIT'])
    const summary = lowestSummary([direct, jit])
    expect(summary[1].metric).toBe('hours_to_berth')
    expect(summary[1].scenarioTypes).toEqual(['DIRECT', 'DIRECT_JIT'])
  })

  it('선석 대기가 없으면 접안까지 = 항해 시간이고 「가장 짧음」은 종전 그대로다', () => {
    const plain = scenario('DIRECT', { cii: '5.56', hours: '71.4285', fuel: '89.28' })
    expect(metricValue(plain, 'hours_to_berth')).toBe('71.4285')
    expect(hasBerth([plain])).toBe(false)
    expect(lowestSummary([plain])[1].metric).toBe('duration_hours')
  })

  it('조건 줄은 묘박 연료의 출처 셋을 서로 다른 말로 적고, 선석이 없으면 줄을 내지 않는다', () => {
    const base = {
      hull_condition_percent: null,
      hull_condition_source: 'NOT_SET' as const,
      berth_available_at: '2026-10-29T08:00:00Z',
      hours_until_berth: '80.0000',
    }
    const request = berthConditionText({ ...base, anchorage_daily_foc_ton: 3, anchorage_daily_foc_source: 'REQUEST' })
    const vessel = berthConditionText({ ...base, anchorage_daily_foc_ton: 3, anchorage_daily_foc_source: 'VESSEL' })
    const notSet = berthConditionText({ ...base, anchorage_daily_foc_ton: null, anchorage_daily_foc_source: 'NOT_SET' })
    expect(new Set([request, vessel, notSet]).size).toBe(3)
    // KST로 적는다(`DESIGN_SYSTEM §4.4`) — 08:00Z는 17:00 KST다.
    expect(request).toContain('17:00')
    expect(berthConditionText({ ...base, berth_available_at: null, hours_until_berth: null, anchorage_daily_foc_ton: null, anchorage_daily_foc_source: 'NOT_SET' })).toBeNull()
    expect(berthConditionText(null)).toBeNull()
  })

  it('채택 고지 — 정본 문구 (PRD §6.3) — 바꾸려면 PRD 개정이 먼저다.', () => {
    const base = scenario('DIRECT', { cii: '5.56', hours: '71.4285', fuel: '89.28' })
    expect(berthAdoptNotice(withBerth(base, waiting('8.5714', '80.0000')))).toBe(
      '선석 대기 8.6시간(대기 연료 1.1t)은 항차 계획에 담기지 않습니다.',
    )
    expect(berthAdoptNotice(withBerth(base, waiting('8.5714', '80.0000', '0.0000', null)))).toBe(
      '선석 대기 8.6시간은 항차 계획에 담기지 않습니다.',
    )
  })

  it('대기가 없거나 선석이 없으면 채택 고지를 붙이지 않는다', () => {
    const base = scenario('DIRECT_JIT', { cii: '4.43', hours: '80.0000', fuel: '71.17' })
    expect(berthAdoptNotice(withBerth(base, waiting('0.0000', '80.0000')))).toBeNull()
    expect(berthAdoptNotice(base)).toBeNull()
  })

  it('도달 불가 줄은 필요 속력과 상한을 말한다', () => {
    const text = unreachableText({
      scenario_type: 'DIRECT_JIT',
      scenario_name: '직항 · 도착시각 맞춤',
      distance_nm: 1000,
      required_speed_kn: 100,
    })
    expect(text).toContain('직항 · 도착시각 맞춤')
    expect(text).toContain('100')
    expect(text).toContain('60')
  })

  it('경고 귀속 — 코드마다 그 경고가 붙은 시나리오 이름을 모은다', () => {
    const a = { ...scenario('DIRECT_JIT', { cii: '1', hours: '1', fuel: '1' }), scenario_name: '직항 · 도착시각 맞춤', warnings: ['ARRIVAL_SPEED_FLOOR'] }
    const b = { ...scenario('DETOUR_JIT', { cii: '1', hours: '1', fuel: '1' }), scenario_name: '우회 · 도착시각 맞춤', warnings: ['ARRIVAL_SPEED_FLOOR'] }
    const c = scenario('DIRECT', { cii: '1', hours: '1', fuel: '1' })
    expect(scenarioWarningOwners([a, b, c])).toEqual({
      ARRIVAL_SPEED_FLOOR: '직항 · 도착시각 맞춤 · 우회 · 도착시각 맞춤',
    })
  })
})
