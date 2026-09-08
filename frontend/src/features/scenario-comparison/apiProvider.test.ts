import { describe, expect, it, vi } from 'vitest'
import { createApiScenarioProvider } from './apiProvider'
import { ScenarioComparisonError } from './provider'
import type { ScenarioComparisonRequest } from './types'

/**
 * 기능② 실 API provider 계약 (`API_SPEC §5.1` · #139).
 *
 * **서버 응답 형태가 화면 타입과 다르다** — 서버는 `required_cii`와
 * `transport_capacity_basis`를 시나리오마다 싣고, 화면은 최상위에서 하나만 쓴다.
 * 그 평탄화가 이 파일이 고정하는 계약이다.
 */

const REQUEST: ScenarioComparisonRequest = {
  vessel_id: '00000000-0000-4000-8000-000000000003',
  regulation_year: 2026,
  base_distance_nm: 1000,
  base_speed_kn: 12.8,
  base_daily_foc_ton: 26.88,
  fuel_type: 'HFO',
}

/** 실제 서버 응답에서 가져온 형태 (2026-08-17 실측). */
const OK_BODY = {
  data: {
    scenarios: [
      {
        scenario_id: 'a',
        scenario_type: 'DIRECT',
        scenario_name: '직항',
        distance_nm: 1000.0,
        speed_kn: 12.8,
        duration_hours: '78.1250',
        fuel_ton: '87.50',
        co2_emission_ton: '272.48',
        attained_cii: '42.535870',
        required_cii: '17.374582',
        ratio_to_required: '2.44817',
        estimated_rating: 'E',
        risk_level: 'CRITICAL',
        next_worse_boundary_margin_ratio: null,
        calculation_basis: {
          ship_type: 'GENERAL_CARGO_SHIP',
          transport_capacity_basis: 'DWT',
        },
      },
      {
        scenario_id: 'b',
        scenario_type: 'SLOW_STEAMING',
        scenario_name: '감속',
        distance_nm: 1000.0,
        speed_kn: 11.8,
        duration_hours: '84.7458',
        fuel_ton: '74.36',
        co2_emission_ton: '231.55',
        attained_cii: '36.149259',
        required_cii: '17.374582',
        ratio_to_required: '2.08059',
        estimated_rating: 'E',
        risk_level: 'CRITICAL',
        next_worse_boundary_margin_ratio: null,
        calculation_basis: {
          ship_type: 'GENERAL_CARGO_SHIP',
          transport_capacity_basis: 'DWT',
        },
      },
    ],
    summary: { lowest_cii_scenarios: ['SLOW_STEAMING'] },
  },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('요청 매핑', () => {
  it('화면 필드를 API_SPEC §5.1 이름으로 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/scenarios/compare')
    const sent = JSON.parse((init as RequestInit).body as string)
    expect(sent).toMatchObject({
      vessel_id: REQUEST.vessel_id,
      regulation_year: 2026,
      current_speed_kn: 12.8,
      direct_distance_nm: 1000,
      base_daily_foc_ton: 26.88,
      fuel_type: 'HFO',
    })
  })

  it('총 연료량을 보내지 않는다 — 서버 계약은 일일 소모량이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    const sent = JSON.parse(
      (fetchImpl.mock.calls[0][1] as RequestInit).body as string,
    )
    expect(sent).not.toHaveProperty('base_fuel_ton')
  })
})

describe('응답 매핑', () => {
  it('시나리오를 순서대로 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.scenarios).toHaveLength(2)
    expect(result.scenarios[0]).toMatchObject({
      scenario_type: 'DIRECT',
      scenario_name: '직항',
      estimated_rating: 'E',
      risk_level: 'CRITICAL',
    })
  })

  it('시나리오마다 실린 공통 값을 최상위로 올린다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.required_cii).toBe('17.374582')
    expect(result.transport_capacity_basis).toBe('DWT')
    expect(result.ship_type).toBe('GENERAL_CARGO_SHIP')
  })

  it('Layer 1 값을 문자열 그대로 둔다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    // 되돌리면 API_SPEC §1.7이 문자열 직렬화로 지킨 정밀도가 사라진다.
    expect(result.scenarios[0].attained_cii).toBe('42.535870')
    expect(typeof result.scenarios[0].fuel_ton).toBe('string')
  })
})

describe('실패 경로', () => {
  it('422 검증 오류의 field를 옮긴다 — 화면이 입력창에 붙일 수 있어야 한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: '기준 일일 연료소모량이 필요합니다.',
            details: [{ field: 'base_daily_foc_ton', message: '필요합니다.' }],
          },
        },
        422,
      ),
    )

    await expect(createApiScenarioProvider(fetchImpl).compare(REQUEST)).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
      field: 'base_daily_foc_ton',
    })
  })

  it('404는 UNSUPPORTED_VESSEL로 옮긴다', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ error: { code: 'NOT_FOUND' } }, 404))
    await expect(createApiScenarioProvider(fetchImpl).compare(REQUEST)).rejects.toMatchObject({
      code: 'UNSUPPORTED_VESSEL',
    })
  })

  it('네트워크 실패를 삼키지 않고 원인을 보존한다', async () => {
    const cause = new TypeError('Failed to fetch')
    const fetchImpl = vi.fn().mockRejectedValue(cause)

    const promise = createApiScenarioProvider(fetchImpl).compare(REQUEST)
    await expect(promise).rejects.toBeInstanceOf(ScenarioComparisonError)
    await expect(promise).rejects.toMatchObject({ cause })
  })

  it('시나리오가 비면 오류다 — 빈 화면을 그리지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: { scenarios: [] } }))
    await expect(createApiScenarioProvider(fetchImpl).compare(REQUEST)).rejects.toThrow(
      /비어 있습니다/,
    )
  })
})

/*
 * 서버가 보낸 경고·면책 문구를 버리지 않는다 (#821).
 *
 * 종전 provider는 `warnings: []`와 접두 `본 결과는 `이 붙은 별도 문자열을 넣었다.
 * 화면의 배너 조건이 **영구 거짓**이 되어 「공식 CII 적용 대상이 아닐 수 있다」·
 * 「기상 보정 없이 계산했다」가 이 화면에서만 사라졌다.
 *
 * ⚠️ **이 파일의 기존 검사는 그 결함을 하나도 잡지 못했다.** 응답 평탄화만 봤고
 * 버려지는 필드는 단언하지 않았다 — 그래서 결함이 살아남았다.
 */
describe('서버 경고·면책 문구 (#821)', () => {
  /** `API_SPEC §5.1` — 최상위에 실린다(`data` 안이 아니다). */
  const WITH_WARNINGS = {
    ...OK_BODY,
    warnings: ['REFERENCE_ONLY', 'NON_CII_VESSEL', 'WEATHER_NONE_FALLBACK'],
    disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
  }

  it('경고 코드를 그대로 넘긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(WITH_WARNINGS))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.warnings).toEqual([
      'REFERENCE_ONLY',
      'NON_CII_VESSEL',
      'WEATHER_NONE_FALLBACK',
    ])
  })

  it('모르는 코드도 거르지 않는다 — 조용히 감추면 경고가 사라진다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ ...OK_BODY, warnings: ['BRAND_NEW_CODE'] }),
    )
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.warnings).toEqual(['BRAND_NEW_CODE'])
  })

  it('면책 문구를 서버 값 그대로 쓴다 — 접두사를 붙이지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(WITH_WARNINGS))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.disclaimer).toBe(
      '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
    )
    expect(result.disclaimer.startsWith('본 결과는')).toBe(false)
  })

  it('서버가 두 필드를 빼면 빈 값이다 — 여기서 기본 문구를 만들지 않는다', async () => {
    /*
     * 기본 문구는 `DisclaimerBanner`가 `PRD §6.3`에서 한 번만 정의한다. 여기서
     * 또 두면 **같은 문구가 두 곳**이 되어 다시 갈린다 — 그것이 이 결함의 모양이었다.
     */
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiScenarioProvider(fetchImpl).compare(REQUEST)

    expect(result.warnings).toEqual([])
    expect(result.disclaimer).toBe('')
  })
})
