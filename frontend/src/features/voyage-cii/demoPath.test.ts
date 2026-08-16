import { describe, expect, it } from 'vitest'
import { DISPLAY_DIGITS, formatDecimalString, formatGrouped, formatPercent } from '../../display/format'
import { createDemoProvider } from './demoProvider'
import { initialFormState, toRequest, validateForm, type VoyageCiiFormState } from './formRules'
import { ciiUnit, marginDisplay, riskLabel } from './resultRules'
import { createDemoScenarioProvider } from '../scenario-comparison/demoProvider'
import { lowestSummary } from '../scenario-comparison/comparisonRules'
import { createDemoAnnualProvider } from '../annual-simulation/demoProvider'

/**
 * 데모 경로의 **화면 표시값**을 고정한다 (#137).
 *
 * 폼 상태에서 출발해 provider를 거쳐 표시 유틸까지 통과한 **최종 문자열**을 단언한다.
 * 다른 테스트는 각 계층을 따로 보지만, 이 파일은 **사람이 화면에서 실제로 읽는 값**을
 * 본다 — 계층별로는 전부 맞는데 합쳐 놓으면 틀린 경우를 잡기 위해서다.
 *
 * 시연 확인용 체크리스트가 이 값들을 그대로 옮겨 적고 있으므로, **이 테스트가 깨지면
 * 그 체크리스트도 낡았다는 신호**다. 표시 규칙(`format.ts`) · 고정표
 * (`referenceTable.ts`) · 표시 문구(`resultRules.ts`) 중 하나가 바뀐 것이다.
 */

const provider = createDemoProvider()

/** 폼 상태에서 출발해 화면에 보이는 문자열까지 만든다. 화면과 같은 경로다. */
async function runVoyage(state: Partial<VoyageCiiFormState>) {
  const form: VoyageCiiFormState = {
    ...initialFormState(),
    distanceNm: '1000',
    speedKn: '14.2',
    fuelType: 'HFO',
    fuelTon: '80',
    ...state,
  }
  expect(validateForm(form)).toEqual({})

  const data = (await provider.estimate(toRequest(form))).data
  return {
    cii: formatDecimalString(data.attained_cii, DISPLAY_DIGITS.cii),
    requiredCii: formatDecimalString(data.required_cii, DISPLAY_DIGITS.cii),
    co2: formatGrouped(data.co2_emission_ton, DISPLAY_DIGITS.co2Ton),
    fuel: formatGrouped(data.fuel_consumption_ton, DISPLAY_DIGITS.fuelTon),
    distance: formatGrouped(String(data.distance_nm), DISPLAY_DIGITS.distanceNm),
    ratio: `${formatPercent(data.ratio_to_required)}%`,
    rating: data.estimated_rating,
    risk: riskLabel(data.risk_level).text,
    riskIcon: riskLabel(data.risk_level).withIcon,
    margin: marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio).text,
    unit: ciiUnit(data.transport_capacity_basis),
  }
}

describe('기준 시나리오 — 체크리스트 §2', () => {
  it('거리 1,000 nm · HFO 80 t · 속력 14.2 kn', async () => {
    expect(await runVoyage({})).toEqual({
      cii: '4.982',
      requiredCii: '5.045',
      co2: '249.1',
      fuel: '80.0',
      distance: '1,000',
      ratio: '98.8%',
      rating: 'C',
      risk: '보통 MEDIUM',
      riskIcon: false,
      margin: 'D 등급까지 7.2%',
      unit: 'gCO₂/(DWT·nm)',
    })
  })
})

describe('A. 연료량 변경 — CO₂와 CII가 같은 방향으로 움직인다', () => {
  it.each([
    ['85', '5.294', '264.7', 'C', '높음 HIGH', 'D 등급까지 1.1%'],
    ['90', '5.605', '280.3', 'D', '높음 HIGH', 'E 등급까지 6.9%'],
    ['70', '4.360', '218.0', 'B', '낮음 LOW', 'C 등급까지 7.6%'],
  ])('연료 %s t → CII %s · CO₂ %s t · %s', async (fuelTon, cii, co2, rating, risk, margin) => {
    const r = await runVoyage({ fuelTon })
    expect([r.cii, r.co2, r.rating, r.risk, r.margin]).toEqual([cii, co2, rating, risk, margin])
    expect(r.distance).toBe('1,000')
  })
})

describe('B. 거리만 변경 — CO₂는 그대로, CII만 반대 방향', () => {
  it.each([
    ['1100', '4.529', 'B', '보통 MEDIUM', 'C 등급까지 4.2%'],
    ['1200', '4.152', 'A', '보통 MEDIUM', 'B 등급까지 3.7%'],
    ['900', '5.536', 'D', '높음 HIGH', 'E 등급까지 8.3%'],
  ])('거리 %s nm → CII %s · %s', async (distanceNm, cii, rating, risk, margin) => {
    const r = await runVoyage({ distanceNm })
    // 거리를 바꿨는데 CO₂가 그대로인 것은 정상이다 — 오류로 판단하지 않는다.
    expect(r.co2).toBe('249.1')
    expect([r.cii, r.rating, r.risk, r.margin]).toEqual([cii, rating, risk, margin])
  })
})

describe('C. 연료 종류 변경 — CF에 따라 CO₂와 CII가 함께 변한다', () => {
  it.each([
    ['LNG', '4.400', '220.0', 'B', '낮음 LOW'],
    ['DIESEL_GAS_OIL', '5.130', '256.5', 'C', '보통 MEDIUM'],
    ['METHANOL', '2.200', '110.0', 'A', '낮음 LOW'],
  ])('%s → CII %s · CO₂ %s t · %s', async (fuelType, cii, co2, rating, risk) => {
    const r = await runVoyage({ fuelType })
    expect([r.cii, r.co2, r.rating, r.risk]).toEqual([cii, co2, rating, risk])
    // 연료량 자체는 그대로다 — 바뀐 것은 CF다.
    expect(r.fuel).toBe('80.0')
  })
})

describe('D·E. 등급 경계 — 1 t 차이로 넘어간다', () => {
  it('A/B 경계 — 69 t는 A, 70 t는 B', async () => {
    expect((await runVoyage({ fuelTon: '69' })).rating).toBe('A')
    expect((await runVoyage({ fuelTon: '70' })).rating).toBe('B')
  })

  it('C/D 경계 — 85 t는 C, 86 t는 D', async () => {
    expect((await runVoyage({ fuelTon: '85' })).rating).toBe('C')
    expect((await runVoyage({ fuelTon: '86' })).rating).toBe('D')
  })

  it('위험도도 함께 바뀐다 — 80 t 보통, 85 t 높음', async () => {
    expect((await runVoyage({ fuelTon: '80' })).risk).toBe('보통 MEDIUM')
    expect((await runVoyage({ fuelTon: '85' })).risk).toBe('높음 HIGH')
  })

  it('HIGH 이상에만 경고 아이콘이 붙는다', async () => {
    expect((await runVoyage({ fuelTon: '80' })).riskIcon).toBe(false)
    expect((await runVoyage({ fuelTon: '85' })).riskIcon).toBe(true)
  })
})

describe('F. 속력만 변경 — 아무것도 바뀌지 않는다', () => {
  it('1.0 kn와 25 kn의 결과가 완전히 같다', async () => {
    // speed_kn은 Layer 1 계산의 피연산자가 아니다. 화면 보조 문구가 사실인지 확인한다.
    const slow = await runVoyage({ speedKn: '1.0' })
    const fast = await runVoyage({ speedKn: '25' })
    expect(slow).toEqual(fast)
    expect(slow.cii).toBe('4.982')
  })
})

describe('G. 최하위 등급 E — 여유율 자리가 문구로 바뀐다', () => {
  it('연료 100 t → E · 심각 CRITICAL · 「해당 없음 — 최하위 등급」', async () => {
    const r = await runVoyage({ fuelTon: '100' })
    expect([r.cii, r.co2, r.rating, r.risk, r.margin]).toEqual([
      '6.228',
      '311.4',
      'E',
      '심각 CRITICAL',
      '해당 없음 — 최하위 등급',
    ])
    expect(r.riskIcon).toBe(true)
  })
})

describe('H. 입력 오류 — 화면 전체가 중단되지 않는다', () => {
  it.each([
    ['distanceNm', '0', '항해거리는 0보다 커야 합니다.'],
    ['speedKn', '0.5', '속도는 1.0노트 이상이어야 합니다.'],
    ['fuelTon', '0', '연료 사용량은 0보다 커야 합니다.'],
    ['fuelType', '', '연료 종류를 선택해 주세요.'],
  ])('%s = %s → 「%s」', (key, value, message) => {
    const form: VoyageCiiFormState = {
      ...initialFormState(),
      distanceNm: '1000',
      speedKn: '14.2',
      fuelType: 'HFO',
      fuelTon: '80',
      [key]: value,
    }
    expect(Object.values(validateForm(form))).toContain(message)
  })

  it('여러 필드가 동시에 잘못되면 전부 표시된다', () => {
    const errors = validateForm({
      ...initialFormState(),
      distanceNm: '0',
      speedKn: '0',
      fuelType: '',
      fuelTon: '0',
    })
    expect(Object.keys(errors)).toHaveLength(4)
  })
})

describe('I. 반복 실행 — 같은 입력에 같은 결과', () => {
  it('세 번 실행해도 같다', async () => {
    const a = await runVoyage({})
    const b = await runVoyage({})
    const c = await runVoyage({})
    expect(a).toEqual(b)
    expect(b).toEqual(c)
  })
})

describe('J. 기능② 시나리오 비교 — 체크리스트 §4', () => {
  it('세 시나리오의 표시값', async () => {
    const result = await createDemoScenarioProvider().compare({
      vessel_id: initialFormState().vesselId,
      regulation_year: 2026,
      base_distance_nm: 1000,
      base_speed_kn: 14,
      base_daily_foc_ton: 26.88,
      fuel_type: 'HFO',
    })

    const rows = result.scenarios.map((s) => [
      s.scenario_name,
      formatGrouped(String(s.distance_nm), DISPLAY_DIGITS.distanceNm),
      String(s.speed_kn),
      formatDecimalString(s.duration_hours, DISPLAY_DIGITS.durationHours),
      formatGrouped(s.fuel_ton, DISPLAY_DIGITS.fuelTon),
      formatGrouped(s.co2_emission_ton, DISPLAY_DIGITS.co2Ton),
      formatDecimalString(s.attained_cii, DISPLAY_DIGITS.cii),
      s.estimated_rating,
      riskLabel(s.risk_level).text,
      marginDisplay(s.estimated_rating, s.next_worse_boundary_margin_ratio).text,
    ])

    expect(rows).toEqual([
      ['직항', '1,000', '14', '71.4', '80.0', '249.1', '4.982', 'C', '보통 MEDIUM', 'D 등급까지 7.2%'],
      ['우회', '1,050', '14', '75.0', '88.0', '274.0', '5.220', 'C', '높음 HIGH', 'D 등급까지 2.5%'],
      ['감속', '1,000', '13', '76.9', '69.0', '214.9', '4.297', 'A', '보통 MEDIUM', 'B 등급까지 0.8%'],
    ])
  })

  it('지표별 최소값 세 줄', async () => {
    const result = await createDemoScenarioProvider().compare({
      vessel_id: initialFormState().vesselId,
      regulation_year: 2026,
      base_distance_nm: 1000,
      base_speed_kn: 14,
      base_daily_foc_ton: 26.88,
      fuel_type: 'HFO',
    })
    expect(lowestSummary(result.scenarios).map((s) => s.scenarioType)).toEqual([
      'SLOW_STEAMING',
      'DIRECT',
      'SLOW_STEAMING',
    ])
  })
})

describe('K. 기능③ 연간 목업 — 체크리스트 §5', () => {
  it('요약 표시값', async () => {
    const r = await createDemoAnnualProvider().load()
    expect({
      distance: formatGrouped(String(r.total_distance_nm), DISPLAY_DIGITS.distanceNm),
      fuel: formatGrouped(r.total_fuel_ton, DISPLAY_DIGITS.fuelTon),
      co2: formatGrouped(r.total_co2_emission_ton, DISPLAY_DIGITS.co2Ton),
      cii: formatDecimalString(r.attained_cii, DISPLAY_DIGITS.cii),
      ratio: `${formatPercent(r.ratio_to_required)}%`,
      rating: r.estimated_rating,
      risk: riskLabel(r.risk_level).text,
      margin: marginDisplay(r.estimated_rating, r.next_worse_boundary_margin_ratio).text,
      sample: r.is_sample_data,
    }).toEqual({
      distance: '25,200',
      fuel: '2,020.0',
      co2: '6,290.3',
      cii: '4.992',
      ratio: '99.0%',
      rating: 'C',
      risk: '보통 MEDIUM',
      margin: 'D 등급까지 7.0%',
      sample: true,
    })
  })

  it('월별 표 6행', async () => {
    const r = await createDemoAnnualProvider().load()
    expect(
      r.months.map((m) => [
        m.month,
        String(m.voyage_count),
        formatGrouped(String(m.distance_nm), DISPLAY_DIGITS.distanceNm),
        formatGrouped(m.fuel_ton, DISPLAY_DIGITS.fuelTon),
        formatGrouped(m.co2_emission_ton, DISPLAY_DIGITS.co2Ton),
        formatDecimalString(m.attained_cii, DISPLAY_DIGITS.cii),
      ]),
    ).toEqual([
      ['2026-01', '3', '4,200', '330.0', '1,027.6', '4.893'],
      ['2026-02', '2', '3,800', '312.0', '971.6', '5.114'],
      ['2026-03', '3', '4,500', '352.0', '1,096.1', '4.872'],
      ['2026-04', '3', '4,100', '340.0', '1,058.8', '5.165'],
      ['2026-05', '4', '4,700', '368.0', '1,146.0', '4.876'],
      ['2026-06', '3', '3,900', '318.0', '990.3', '5.078'],
    ])
  })
})
