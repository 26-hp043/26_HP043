import { describe, expect, it, vi } from 'vitest'
import {
  DISPLAY_DIGITS,
  formatDecimalString,
  formatGrouped,
  formatPercent,
} from '../../display/format'
import { createApiProvider } from './apiProvider'
import { initialFormState, toRequest, validateForm, type VoyageCiiFormState } from './formRules'
import { ciiUnit, marginDisplay, riskLabel } from './resultRules'
import { createApiScenarioProvider } from '../scenario-comparison/apiProvider'
import { toRequest as toComparisonRequest } from '../scenario-comparison/requestRules'
import { lowestSummary } from '../scenario-comparison/comparisonRules'
import { createApiAnnualSimulationProvider } from '../annual-simulation/apiProvider'

/**
 * 실 API 경로의 **화면 표시값**을 고정한다 (#542 PR ②).
 *
 * ## 이 파일이 대신하는 것
 *
 * `demoPath.test.ts`가 폼 상태 → provider → 표시 유틸을 관통하는 유일한 테스트였다.
 * 그러나 그 파일은 **demo provider만** 통과시키므로, 데모 모드가 폐기되면 함께
 * 사라진다. 커버리지를 잃지 않은 상태에서 제거를 시작하려고 먼저 세운다.
 *
 * ## 무엇이 실제로 잠기는가 — 계산은 아니다
 *
 * 서버 응답을 목(mock)으로 주므로 **수치 자체는 이 파일이 정한 값**이다. 계산의
 * 정확성은 백엔드 테스트가 본다. 여기서 잠기는 것은 그 사이의 세 층이다.
 *
 * | 층 | 무엇 |
 * |---|---|
 * | 요청 조립 | 폼 상태가 `API_SPEC §4.1` 요청 본문이 되는가 (`toRequest`) |
 * | 응답 해석 | 서버 필드가 화면 타입으로 옮겨지는가 (`apiProvider`) |
 * | 표시 변환 | 그 값이 `DESIGN_SYSTEM §4` 자릿수로 그려지는가 (`format.ts`) |
 *
 * **세 층 각각은 이미 테스트가 있다.** 이 파일이 보는 것은 합쳐 놓았을 때다 —
 * 계층별로는 전부 맞는데 화면에서 틀린 경우가 실제로 네 번 나왔다(`#563` 선박 상세 ·
 * `#566` 실시간 CII · `#567` 대시보드 · 정박·묘박 기록 패널). 그 넷 모두
 * **provider가 준 원본 문자열을 화면이 그대로 출력**한 것이며, 층별 테스트로는
 * 하나도 잡히지 않았다.
 *
 * ## DOM을 쓰지 않는다
 *
 * `demoPath.test.ts`와 같다. 컴포넌트가 이 함수들을 실제로 부르는지(배선)는 여기서
 * 보지 않으며 `#557`이 별도로 다룬다. 두 파일은 대체 관계가 아니라 다른 층이다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

/** 연료 선택지 — 실 API 모드에서는 서버가 준다 (`#542` PR ①). */
const FUELS = [{ code: 'HFO', displayName: '고유황유' }]

/** `API_SPEC §4.1` 응답. `apiProvider.test.ts`가 쓰는 것과 같은 형태다. */
const VOYAGE_BODY = {
  data: {
    attained_cii: '4.982400',
    required_cii: '5.045066',
    ratio_to_required: '0.98758',
    estimated_rating: 'C',
    next_worse_boundary_margin: '0.365370',
    next_worse_boundary_margin_ratio: '0.0724',
    co2_emission_ton: '249.12',
    fuel_consumption_ton: '80.00',
    distance_nm: 1000,
    risk_level: 'MEDIUM',
    transport_capacity: '50000',
    transport_capacity_basis: 'DWT',
    reference_capacity: '50000',
    reference_capacity_rule: 'DWT',
    calculation_basis: {
      ship_type: 'BULK_CARRIER',
      z_factor_percent: '11',
      fuel_cf_details: [{ fuel_type: 'HFO', cf: '3.114', fuel_ton: '80.0' }],
      a_decimal: '4745',
      c: '0.622',
    },
  },
  parameters_used: {},
  calculation_run_id: '00000000-0000-4000-8000-0000000000a1',
  model_version: { engine: 'dual-precision-v1', decimal_precision: 30 },
  input_hash: 'sha256:' + 'a'.repeat(64),
  parameter_hash: 'sha256:' + 'b'.repeat(64),
  warnings: ['REFERENCE_ONLY'],
  disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
  meta: { request_id: 'r', timestamp: '2026-08-08T00:00:00Z', duration_ms: 4 },
}

/** 폼 상태에서 출발해 화면에 보이는 문자열까지 만든다. 화면과 같은 경로다. */
async function runVoyage(state: Partial<VoyageCiiFormState> = {}) {
  const form: VoyageCiiFormState = {
    ...initialFormState(),
    vesselId: '00000000-0000-4000-8000-000000000001',
    regulationYear: '2026',
    distanceNm: '1000',
    speedKn: '14.2',
    fuelType: 'HFO',
    fuelTon: '80',
    ...state,
  }
  expect(validateForm(form, FUELS)).toEqual({})

  const fetchImpl = vi.fn(async () => jsonResponse(VOYAGE_BODY))
  const data = (await createApiProvider({ fetchImpl }).estimate(toRequest(form))).data

  return {
    request: JSON.parse((fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string),
    cii: formatDecimalString(data.attained_cii, DISPLAY_DIGITS.cii),
    requiredCii: formatDecimalString(data.required_cii, DISPLAY_DIGITS.cii),
    co2: formatGrouped(data.co2_emission_ton, DISPLAY_DIGITS.co2Ton),
    fuel: formatGrouped(data.fuel_consumption_ton, DISPLAY_DIGITS.fuelTon),
    distance: formatGrouped(String(data.distance_nm), DISPLAY_DIGITS.distanceNm),
    ratio: `${formatPercent(data.ratio_to_required)}%`,
    rating: data.estimated_rating,
    risk: riskLabel(data.risk_level).text,
    margin: marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio).text,
    unit: ciiUnit(data.transport_capacity_basis),
  }
}

describe('기능① — 폼에서 출발해 화면 문자열까지', () => {
  it('요청 본문이 API_SPEC §4.1 형태다', async () => {
    const { request } = await runVoyage()

    expect(request).toEqual({
      vessel_id: '00000000-0000-4000-8000-000000000001',
      regulation_year: 2026,
      distance_nm: 1000,
      speed_kn: 14.2,
      fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 80 }],
    })
  })

  it('서버 원본이 §4 자릿수로 그려진다 — 그대로 내보내지 않는다', async () => {
    const shown = await runVoyage()

    // 서버는 소수 6자리로 준다. 화면이 그대로 출력하던 것이 #563·#566·#567이었다.
    expect(shown.cii).toBe('4.982')
    expect(shown.requiredCii).toBe('5.045')
    expect(shown.co2).toBe('249.1')
    expect(shown.fuel).toBe('80.0')
    expect(shown.distance).toBe('1,000')
    expect(shown.ratio).toBe('98.8%')
  })

  it('등급·위험도·여유율 문구가 함께 나온다', async () => {
    const shown = await runVoyage()

    expect(shown.rating).toBe('C')
    expect(shown.risk).toBe('보통 MEDIUM')
    expect(shown.margin).toBe('D 등급까지 7.2%')
  })

  it('CII 단위는 capacity 축에서 나온다 — 고정 문자열이 아니다', async () => {
    const shown = await runVoyage()

    expect(shown.unit).toContain('DWT')
  })

  it('같은 입력에 같은 표시값이 나온다', async () => {
    expect(await runVoyage()).toEqual(await runVoyage())
  })
})

const COMPARISON_BODY = {
  data: {
    scenarios: [
      {
        scenario_id: 'a',
        scenario_type: 'DIRECT',
        scenario_name: '직항',
        distance_nm: 1000.0,
        speed_kn: 14,
        duration_hours: '71.4286',
        fuel_ton: '80.00',
        co2_emission_ton: '249.12',
        attained_cii: '4.982400',
        required_cii: '5.045066',
        ratio_to_required: '0.98758',
        estimated_rating: 'C',
        risk_level: 'MEDIUM',
        next_worse_boundary_margin_ratio: '0.0724',
        calculation_basis: { ship_type: 'BULK_CARRIER', transport_capacity_basis: 'DWT' },
      },
      {
        scenario_id: 'b',
        scenario_type: 'SLOW_STEAMING',
        scenario_name: '감속',
        distance_nm: 1000.0,
        speed_kn: 13,
        duration_hours: '76.9231',
        fuel_ton: '69.00',
        co2_emission_ton: '214.87',
        attained_cii: '4.297400',
        required_cii: '5.045066',
        ratio_to_required: '0.85180',
        estimated_rating: 'A',
        risk_level: 'MEDIUM',
        next_worse_boundary_margin_ratio: '0.0080',
        calculation_basis: { ship_type: 'BULK_CARRIER', transport_capacity_basis: 'DWT' },
      },
    ],
    summary: { lowest_cii_scenario: 'SLOW_STEAMING' },
  },
}

describe('기능② — 비교 결과가 표 문자열이 된다', () => {
  async function compare() {
    const fetchImpl = vi.fn(async () => jsonResponse(COMPARISON_BODY))
    return createApiScenarioProvider(fetchImpl).compare(
      toComparisonRequest(
        {
          vesselId: '00000000-0000-4000-8000-000000000001',
          regulationYear: '2026',
          baseDistanceNm: '1000',
          baseSpeedKn: '14',
          baseDailyFocTon: '26.88',
          fuelType: 'HFO',
        },
        FUELS,
      ),
    )
  }

  it('각 행이 §4 자릿수로 그려진다', async () => {
    const result = await compare()

    const rows = result.scenarios.map((s) => [
      s.scenario_name,
      formatGrouped(String(s.distance_nm), DISPLAY_DIGITS.distanceNm),
      formatDecimalString(s.duration_hours, DISPLAY_DIGITS.durationHours),
      formatGrouped(s.fuel_ton, DISPLAY_DIGITS.fuelTon),
      formatGrouped(s.co2_emission_ton, DISPLAY_DIGITS.co2Ton),
      formatDecimalString(s.attained_cii, DISPLAY_DIGITS.cii),
      s.estimated_rating,
      riskLabel(s.risk_level).text,
      marginDisplay(s.estimated_rating, s.next_worse_boundary_margin_ratio).text,
    ])

    expect(rows).toEqual([
      ['직항', '1,000', '71.4', '80.0', '249.1', '4.982', 'C', '보통 MEDIUM', 'D 등급까지 7.2%'],
      ['감속', '1,000', '76.9', '69.0', '214.9', '4.297', 'A', '보통 MEDIUM', 'B 등급까지 0.8%'],
    ])
  })

  it('지표별 최소값을 고른다 — CII·소요시간·연료 순서다', async () => {
    const result = await compare()

    // 감속이 CII·연료는 낮지만 **소요시간은 길다.** 세 지표가 같은 시나리오를
    // 가리키지 않는 픽스처라야 순서가 실제로 잠긴다.
    expect(lowestSummary(result.scenarios).map((s) => s.scenarioType)).toEqual([
      'SLOW_STEAMING',
      'DIRECT',
      'SLOW_STEAMING',
    ])
  })
})

const ANNUAL_BODY = {
  data: {
    simulation_id: 'sim-1',
    calculation_run_id: 'run-1',
    deterministic: {
      projected_attained_cii: '5.0248000000',
      projected_rating: 'C',
      completed_voyage_count: 8,
      remaining_voyage_count: 4,
      completed_M_gco2: '6290280000',
      completed_W_capacity_nm: '1260000000',
      planned_M_gco2: '3145140000',
      planned_W_capacity_nm: '630000000',
    },
    monte_carlo: {
      rng_metadata: {
        seed_entropy: '0x00000000000000000000000000003039',
        bit_generator: 'PCG64DXSM',
        numpy_version: '2.1.0',
        python_version: '3.12.4',
        platform: 'Linux',
      },
      runs: 5000,
      rating_probabilities: { A: '0.0200', B: '0.2800', C: '0.5500', D: '0.1300', E: '0.0200' },
      target_success_probability: '0.3000',
      target_rating: 'B',
      p10: '4.7100',
      p50: '5.0400',
      p90: '5.4200',
      mean_cii: '5.0600',
    },
    risk_level: 'HIGH',
    sensitivity_analysis: { interaction_note: '개별 효과만 표시합니다.' },
    snapshot: { snapshot_id: 'snap-1', created_at: '2026-08-17T00:00:00Z', voyage_count: 12 },
    warnings: ['REFERENCE_ONLY'],
  },
  meta: { request_id: 'r', timestamp: 't' },
}

describe('기능③ — 연간 시뮬레이션 표시값', () => {
  async function run() {
    const fetchImpl = vi.fn(async () => jsonResponse(ANNUAL_BODY))
    return createApiAnnualSimulationProvider({ fetchImpl }).run({
      vessel_id: '00000000-0000-4000-8000-000000000001',
      regulation_year: 2026,
      target_rating: 'B',
      simulation_runs: 5000,
    })
  }

  it('결정론 표시값이 §4.1 3자리로 그려진다', async () => {
    const r = await run()

    expect({
      cii: formatDecimalString(r.deterministic.projected_attained_cii, DISPLAY_DIGITS.cii),
      rating: r.deterministic.projected_rating,
      completed: r.deterministic.completed_voyage_count,
      remaining: r.deterministic.remaining_voyage_count,
      risk: riskLabel(r.risk_level).text,
    }).toEqual({
      cii: '5.025',
      rating: 'C',
      completed: 8,
      remaining: 4,
      risk: '높음 HIGH',
    })
  })

  it('확률은 문자열 그대로 유지된다 — 백분율 환산은 표시 시점에만 한다', async () => {
    const r = await run()
    const p = r.monte_carlo.rating_probabilities

    expect([p.A, p.B, p.C, p.D, p.E]).toEqual(['0.0200', '0.2800', '0.5500', '0.1300', '0.0200'])
    expect(formatPercent(r.monte_carlo.target_success_probability)).toBe('30.0')
  })

  it('실 API 결과에는 샘플 배지가 붙지 않는다', async () => {
    // demo provider는 `is_sample_data: true`를 달았다. 실 API 응답에는 그 표시가
    // 없어야 한다 — `PRD R-5` 배지가 실제 데이터에 붙으면 신뢰가 반대로 깎인다.
    expect((await run()).is_sample_data).toBeFalsy()
  })
})
