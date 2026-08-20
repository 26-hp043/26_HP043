import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  MALFORMED_ERROR_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  SESSION_EXPIRED_MESSAGE,
  createApiVesselRegistrationProvider,
  toVesselRegistrationError,
} from './apiProvider'
import { VesselRegistrationError } from './provider'
import type { VesselCreateRequest } from './types'

/**
 * 선박 등록 실 API provider 검증 (#441).
 *
 * **`fetch`를 주입해 서버 없이 돈다.** 확인하는 것은 「서버가 이렇게 응답하면 화면이
 * 무엇을 받는가」이며, 서버가 그 형태를 내는지는 백엔드 테스트가 잠근다.
 */

/** `API_SPEC §2.1` 선박 객체. 제원 없이 등록된 경우를 기본값으로 둔다. */
const CREATED = {
  id: '00000000-0000-4000-8000-0000000000a1',
  imo_number: '9440001',
  name: 'PACIFIC STAR',
  ship_type: 'BULK_CARRIER',
  gross_tonnage: null,
  deadweight: null,
  default_fuel_type: null,
  reference_speed_kn: null,
  reference_daily_foc_ton: null,
  is_cii_applicable_hint: false,
  underway_state: null,
  detail_status: null,
  current_lat: null,
  current_lon: null,
  position_updated_at: null,
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
}

const REQUEST: VesselCreateRequest = {
  imo_number: '9440001',
  name: 'PACIFIC STAR',
  ship_type: 'BULK_CARRIER',
}

function jsonResponse(body: unknown, status = 201): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

function errorBody(code: string, message: string, field?: string) {
  return {
    error: {
      code,
      message,
      ...(field ? { details: [{ field, field_label: '재화중량톤수', message }] } : {}),
    },
    meta: { request_id: 'r', timestamp: '2026-08-17T00:00:00Z' },
  }
}

describe('요청 전송', () => {
  it('POST /api/v1/vessels 로 보낸다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    await createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST)

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${DEFAULT_API_BASE_URL}/vessels`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual(REQUEST)
  })

  it('base URL을 덮어쓸 수 있다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    await createApiVesselRegistrationProvider({
      baseUrl: 'https://example.test/api/v1',
      fetchImpl,
    }).register(REQUEST)

    const [url] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://example.test/api/v1/vessels')
  })

  it('API Key가 없으면 헤더를 붙이지 않는다 — 빈 값은 「틀린 키」로 읽힐 수 있다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    await createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST)

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-API-Key']).toBeUndefined()
  })

  it('API Key가 있으면 싣는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    await createApiVesselRegistrationProvider({ fetchImpl, apiKey: 'k' }).register(REQUEST)

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe('k')
  })
})

describe('성공 응답', () => {
  it('`data`를 가공하지 않고 그대로 돌려준다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    const vessel = await createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST)
    expect(vessel).toEqual(CREATED)
  })

  it('제원이 `null`인 응답을 그대로 유지한다 — 미입력을 0으로 바꾸지 않는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: CREATED }))
    const vessel = await createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST)
    expect(vessel.deadweight).toBeNull()
    expect(vessel.gross_tonnage).toBeNull()
  })

  it('201인데 본문이 계약과 다르면 성공으로 처리하지 않는다', async () => {
    // 등록됐는지 알 수 없는 상태를 「등록 완료」로 보이면 사용자가 같은 배를 두 번 등록한다.
    const fetchImpl = vi.fn(async () => jsonResponse({ vessel: CREATED }))
    await expect(
      createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST),
    ).rejects.toThrow(MALFORMED_ERROR_MESSAGE)
  })
})

describe('오류 매핑', () => {
  it('422 VALIDATION_ERROR의 필드 경로를 그대로 넘긴다', () => {
    const error = toVesselRegistrationError(
      422,
      errorBody('VALIDATION_ERROR', '0보다 커야 합니다.', 'deadweight'),
    )
    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.field).toBe('deadweight')
  })

  it('409 CONFLICT는 전용 코드로 남긴다 — 파라미터 문제와 섞지 않는다 (#286)', () => {
    const error = toVesselRegistrationError(
      409,
      errorBody('CONFLICT', '이미 등록된 IMO 번호입니다: 9440001'),
    )
    expect(error.code).toBe('CONFLICT')
  })

  it('같은 409의 PARAMETER_ERROR는 사용자가 고칠 수 없는 실패로 분류한다', () => {
    const error = toVesselRegistrationError(409, errorBody('PARAMETER_ERROR', '파라미터 없음'))
    expect(error.code).toBe('REGISTRATION_ERROR')
  })

  it('모르는 코드는 일반 실패로 떨어뜨린다', () => {
    expect(toVesselRegistrationError(500, errorBody('TEAPOT', '?')).code).toBe(
      'REGISTRATION_ERROR',
    )
  })

  it('오류 본문 형태가 깨져 있어도 예외를 만들어 낸다', () => {
    const error = toVesselRegistrationError(500, { detail: 'nope' })
    expect(error.code).toBe('REGISTRATION_ERROR')
    expect(error.message).toContain('HTTP 500')
  })

  it('401은 세션 만료로 알린다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}, 401))
    await expect(
      createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST),
    ).rejects.toThrow(SESSION_EXPIRED_MESSAGE)
  })

  it('네트워크 실패를 그대로 노출하지 않는다', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    await expect(
      createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST),
    ).rejects.toThrow(NETWORK_ERROR_MESSAGE)
  })

  it('실패는 모두 `VesselRegistrationError`다 — 화면이 한 종류만 다룬다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(errorBody('CONFLICT', '중복'), 409))
    await expect(
      createApiVesselRegistrationProvider({ fetchImpl }).register(REQUEST),
    ).rejects.toBeInstanceOf(VesselRegistrationError)
  })
})
