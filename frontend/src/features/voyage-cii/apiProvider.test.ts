import { describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_API_BASE_URL,
  MALFORMED_ERROR_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  createApiProvider,
  toVoyageCiiError,
} from './apiProvider'
import { VoyageCiiError } from './provider'
import { createVoyageCiiProvider, isEnabled, shouldUseApi } from './providerSelection'
import { initialFormState, toRequest } from './formRules'

/**
 * 실 API provider 검증 (#138).
 *
 * **`fetch`를 주입해 서버 없이 돈다.** 확인하는 것은 「서버가 이렇게 응답하면 화면이
 * 무엇을 받는가」이며, 서버가 그 형태를 내는지는 백엔드 테스트(`tests/test_voyage_cii_api.py`)가
 * 잠근다.
 */

/** `#132` 계약과 같은 응답 본문. 백엔드 테스트가 이 값을 단언한다. */
const OK_BODY = {
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

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const REQUEST = toRequest({
  ...initialFormState(),
  distanceNm: '1000',
  speedKn: '14.2',
  fuelType: 'HFO',
  fuelTon: '80',
})

describe('요청 전송', () => {
  it('POST /api/v1/calculations/voyage-cii 로 보낸다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(OK_BODY))
    await createApiProvider({ fetchImpl }).estimate(REQUEST)

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${DEFAULT_API_BASE_URL}/calculations/voyage-cii`)
    expect(init.method).toBe('POST')
  })

  it('요청 본문이 계약 필드 그대로다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(OK_BODY))
    await createApiProvider({ fetchImpl }).estimate(REQUEST)

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    const sent = JSON.parse(init.body as string)
    expect(Object.keys(sent).sort()).toEqual([
      'distance_nm',
      'fuel_uses',
      'regulation_year',
      'speed_kn',
      'vessel_id',
    ])
    expect(sent.fuel_uses).toEqual([{ fuel_type: 'HFO', fuel_ton: 80 }])
  })

  it('base URL이 상대 경로다 — 배포 환경마다 바꾸지 않아도 된다', () => {
    expect(DEFAULT_API_BASE_URL.startsWith('/')).toBe(true)
  })

  it('API Key가 없으면 헤더를 붙이지 않는다', async () => {
    // 빈 값을 보내면 서버가 「키가 있는데 틀렸다」로 볼 수 있다.
    const fetchImpl = vi.fn(async () => jsonResponse(OK_BODY))
    await createApiProvider({ fetchImpl }).estimate(REQUEST)
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.headers).not.toHaveProperty('X-API-Key')
  })

  it('API Key가 있으면 헤더로 주입한다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(OK_BODY))
    await createApiProvider({ fetchImpl, apiKey: 'k-1' }).estimate(REQUEST)
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe('k-1')
  })
})

describe('성공 응답', () => {
  it('본문을 그대로 넘긴다 — Layer 1 문자열을 손대지 않는다', async () => {
    // 되돌리거나 재직렬화하면 API_SPEC §1.7이 지킨 정밀도가 사라진다.
    const fetchImpl = vi.fn(async () => jsonResponse(OK_BODY))
    const result = await createApiProvider({ fetchImpl }).estimate(REQUEST)
    expect(result).toEqual(OK_BODY)
    expect(result.data.attained_cii).toBe('4.982400')
    expect(typeof result.data.attained_cii).toBe('string')
  })
})

describe('오류 변환 — 화면은 VoyageCiiError만 안다', () => {
  it('422 필드 오류가 해당 입력창 경로를 그대로 들고 온다', () => {
    const error = toVoyageCiiError(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: '연료 사용량은 0보다 커야 합니다.',
        details: [
          {
            field: 'fuel_uses[0].fuel_ton',
            field_label: '연료 사용량',
            message: '연료 사용량은 0보다 커야 합니다.',
          },
        ],
      },
    })
    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.field).toBe('fuel_uses[0].fuel_ton')
  })

  it('409 PARAMETER_ERROR를 CALCULATION_ERROR로 옮긴다', () => {
    // 화면에 PARAMETER_ERROR가 없다. 「사용자가 입력으로 고칠 수 없다」는 성질은 같다.
    const error = toVoyageCiiError(409, {
      error: { code: 'PARAMETER_ERROR', message: '해당 연도의 규정 파라미터가 없습니다.' },
    })
    expect(error.code).toBe('CALCULATION_ERROR')
    expect(error.message).toContain('규정 파라미터')
  })

  it('404를 UNSUPPORTED_VESSEL로 옮긴다', () => {
    const error = toVoyageCiiError(404, {
      error: { code: 'NOT_FOUND', message: '선박을 찾을 수 없습니다.' },
    })
    expect(error.code).toBe('UNSUPPORTED_VESSEL')
  })

  it('500 INTERNAL_ERROR도 화면이 아는 코드로 옮긴다', () => {
    const error = toVoyageCiiError(500, {
      error: { code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했습니다.' },
    })
    expect(error.code).toBe('CALCULATION_ERROR')
  })

  it('모르는 서버 코드도 삼키지 않는다', () => {
    const error = toVoyageCiiError(422, {
      error: { code: 'MODEL_BREAKDOWN_ERROR', message: '기상 조건이 가혹합니다.' },
    })
    expect(error.code).toBe('CALCULATION_ERROR')
    expect(error.message).toBe('기상 조건이 가혹합니다.')
  })

  it('오류 응답 형태가 깨져도 VoyageCiiError를 낸다', () => {
    const error = toVoyageCiiError(500, { unexpected: true })
    expect(error).toBeInstanceOf(VoyageCiiError)
    expect(error.message).toContain(MALFORMED_ERROR_MESSAGE)
    expect(error.message).toContain('500')
  })

  it('details가 없으면 field가 undefined다 — 폼 상단에 표시된다', () => {
    const error = toVoyageCiiError(409, {
      error: { code: 'PARAMETER_ERROR', message: 'x' },
    })
    expect(error.field).toBeUndefined()
  })
})

describe('전송 계층 실패', () => {
  it('네트워크 실패를 사용자 문구로 바꾼다', async () => {
    // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    const error = await createApiProvider({ fetchImpl })
      .estimate(REQUEST)
      .then(() => null, (e: unknown) => e as VoyageCiiError)

    expect(error).toBeInstanceOf(VoyageCiiError)
    expect(error?.message).toBe(NETWORK_ERROR_MESSAGE)
  })

  it('원인 예외를 cause로 남긴다 — 개발자 도구에서 추적할 수 있어야 한다', async () => {
    const cause = new TypeError('Failed to fetch')
    const fetchImpl = vi.fn(async () => {
      throw cause
    })
    const error = await createApiProvider({ fetchImpl })
      .estimate(REQUEST)
      .then(() => null, (e: unknown) => e as VoyageCiiError)

    expect(error?.cause).toBe(cause)
  })

  it('본문이 JSON이 아니면 형태 오류로 처리한다', async () => {
    const fetchImpl = vi.fn(
      async () =>
        ({
          ok: false,
          status: 502,
          json: async () => {
            throw new SyntaxError('Unexpected token <')
          },
        }) as unknown as Response,
    )
    const error = await createApiProvider({ fetchImpl })
      .estimate(REQUEST)
      .then(() => null, (e: unknown) => e as VoyageCiiError)

    expect(error?.message).toContain(MALFORMED_ERROR_MESSAGE)
  })

  it('200인데 본문이 객체가 아니면 거부한다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse('문자열', 200))
    const error = await createApiProvider({ fetchImpl })
      .estimate(REQUEST)
      .then(() => null, (e: unknown) => e as VoyageCiiError)

    expect(error).toBeInstanceOf(VoyageCiiError)
  })
})

describe('provider 전환 — providerSelection', () => {
  it.each([
    ['true', true],
    ['false', false],
    ['1', false],
    ['TRUE', false],
    [undefined, false],
    ['', false],
  ])('VITE_USE_API=%s → %s', (raw, expected) => {
    // .env 값은 전부 문자열이라 Boolean("false")가 true가 되는 함정이 있다.
    expect(isEnabled(raw)).toBe(expected)
  })

  it('기본값은 demo provider다 — 백엔드 없이도 화면이 뜬다', () => {
    const env = {} as ImportMetaEnv
    expect(shouldUseApi(env)).toBe(false)
    expect(createVoyageCiiProvider(env)).toBeDefined()
  })

  it('VITE_USE_API=true 이면 실 API provider를 만든다', () => {
    const env = { VITE_USE_API: 'true' } as unknown as ImportMetaEnv
    expect(shouldUseApi(env)).toBe(true)
    expect(createVoyageCiiProvider(env)).toBeDefined()
  })

  it('두 provider가 같은 인터페이스를 만족한다', () => {
    const demo = createVoyageCiiProvider({} as ImportMetaEnv)
    const api = createVoyageCiiProvider({ VITE_USE_API: 'true' } as unknown as ImportMetaEnv)
    expect(typeof demo.estimate).toBe('function')
    expect(typeof api.estimate).toBe('function')
  })
})
