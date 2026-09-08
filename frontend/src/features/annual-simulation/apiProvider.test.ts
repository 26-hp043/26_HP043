import { describe, expect, it, vi } from 'vitest'
import {
  createApiAnnualSimulationProvider,
  MALFORMED_ERROR_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  toAnnualSimulationError,
} from './apiProvider'
import type { AnnualSimulationRequest } from './types'

const REQUEST: AnnualSimulationRequest = {
  vessel_id: '00000000-0000-4000-8000-000000000001',
  regulation_year: 2026,
  target_rating: 'B',
  simulation_runs: 5000,
}

// `API_SPEC §1.3.1` 계산 결과 응답 봉투 (`#752`) — `calculation_run_id`와 `warnings`는
// **`data` 밖**이다. 기능①·②도 최상위로 낸다.
const OK_BODY = {
  data: {
    simulation_id: 'sim-1',
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
      rating_probabilities: {
        A: '0.0200',
        B: '0.2800',
        C: '0.5500',
        D: '0.1300',
        E: '0.0200',
      },
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
  },
  parameters_used: { regulation_year: { year: '2026', z_factor_percent: '11.0000' } },
  calculation_run_id: 'run-1',
  model_version: { engine: 'annual_simulation' },
  input_hash: 'sha256:aa',
  parameter_hash: 'sha256:bb',
  warnings: ['REFERENCE_ONLY'],
  disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
  meta: { request_id: 'r', timestamp: 't', duration_ms: 2840 },
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('정상 응답', () => {
  it('data 블록을 그대로 넘긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)

    expect(result.deterministic.projected_rating).toBe('C')
    expect(result.monte_carlo.runs).toBe(5000)
    expect(result.snapshot.snapshot_id).toBe('snap-1')
  })

  it('Layer 1 값을 문자열 그대로 둔다', async () => {
    // 되돌리면 `API_SPEC §1.7`이 문자열 직렬화로 지킨 정밀도가 사라진다.
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    const result = await createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)

    expect(result.deterministic.projected_attained_cii).toBe('5.0248000000')
    expect(typeof result.monte_carlo.rating_probabilities.C).toBe('string')
  })

  it('POST로 올바른 경로를 호출한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))
    await createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/annual-simulations')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toMatchObject({ target_rating: 'B', simulation_runs: 5000 })
  })
})

describe('오류', () => {
  it('네트워크 실패를 삼키지 않는다', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)).rejects.toThrow(
      NETWORK_ERROR_MESSAGE,
    )
  })

  it('서버 메시지를 고쳐 쓰지 않는다', () => {
    // `PRD §12.8`이 거부 사유를 문구로 규정하고 서버가 그 문구를 낸다. 화면이 다시
    // 쓰면 두 문구가 갈린다.
    const error = toAnnualSimulationError(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'target_rating은 E를 사용할 수 없습니다.',
        details: [{ field: 'target_rating' }],
      },
    })
    expect(error.message).toBe('target_rating은 E를 사용할 수 없습니다.')
    expect(error.field).toBe('target_rating')
  })

  it('형태가 깨진 오류 응답도 상태 코드를 남긴다', () => {
    const error = toAnnualSimulationError(500, {})
    expect(error.message).toContain(MALFORMED_ERROR_MESSAGE)
    expect(error.message).toContain('500')
  })

  it('data가 없으면 형식 오류다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ meta: {} }))
    await expect(createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)).rejects.toThrow(
      MALFORMED_ERROR_MESSAGE,
    )
  })

  // `#752` — 봉투의 최상위 필드가 빠지면 **조용히 넘어가지 않는다.**
  //
  // 빈 배열·빈 문자열로 채우면 「경고가 없다」와 「경고를 받지 못했다」가 화면에서
  // 같아 보인다. 앞의 것은 정상이고 뒤의 것은 계약 위반이라, 뭉치면 서버가 필드를
  // 빠뜨려도 아무도 모른다 — 이 이슈가 보고한 상태가 정확히 그것이다.
  it.each([
    ['calculation_run_id', { ...OK_BODY, calculation_run_id: undefined }],
    ['warnings', { ...OK_BODY, warnings: undefined }],
    ['calculation_run_id가 문자열이 아님', { ...OK_BODY, calculation_run_id: 42 }],
    ['warnings가 배열이 아님', { ...OK_BODY, warnings: 'REFERENCE_ONLY' }],
  ])('봉투에 %s 문제가 있으면 형식 오류다', async (_label, body) => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body))
    await expect(createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)).rejects.toThrow(
      MALFORMED_ERROR_MESSAGE,
    )
  })

  it('봉투의 최상위 필드를 결과에 합친다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(OK_BODY))

    const result = await createApiAnnualSimulationProvider({ fetchImpl }).run(REQUEST)

    // 화면 타입은 그대로다 — 합치는 자리가 provider 경계다 (`#752`).
    expect(result.calculation_run_id).toBe('run-1')
    expect(result.warnings).toEqual(['REFERENCE_ONLY'])
    expect(result.simulation_id).toBe('sim-1')
  })
})
