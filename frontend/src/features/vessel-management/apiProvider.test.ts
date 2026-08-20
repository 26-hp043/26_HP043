import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  MALFORMED_ERROR_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  createApiVesselManagementProvider,
  readPageMeta,
  toVesselManagementError,
} from './apiProvider'
import { VesselManagementError } from './provider'

/**
 * 선박 관리 실 API provider 검증 (#510).
 *
 * **`fetch`를 주입해 서버 없이 돈다.** 확인하는 것은 「서버가 이렇게 응답하면 화면이
 * 무엇을 받는가」이며, 서버가 그 형태를 내는지는 백엔드 테스트가 잠근다
 * (`vessel-registration/apiProvider.test.ts`와 같은 경계).
 */

const VESSEL = {
  id: '00000000-0000-4000-8000-0000000000a1',
  imo_number: '9448839',
  name: 'STAR SKIPPER',
  ship_type: 'CONTAINER_SHIP',
  gross_tonnage: null,
  deadweight: 9520,
  default_fuel_type: null,
  reference_speed_kn: 16.5,
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

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

function errorBody(code: string, message: string, field?: string) {
  return { error: { code, message, details: field ? [{ field }] : undefined } }
}

describe('list — GET /vessels', () => {
  it('data 배열과 meta의 커서를 함께 돌려준다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: [VESSEL], meta: { next_cursor: 'c2', has_more: true } }),
    )
    const provider = createApiVesselManagementProvider({ fetchImpl })

    const page = await provider.list()

    expect(page.vessels).toHaveLength(1)
    expect(page.nextCursor).toBe('c2')
    expect(page.hasMore).toBe(true)
    expect(fetchImpl).toHaveBeenCalledWith(
      `${DEFAULT_API_BASE_URL}/vessels`,
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    )
  })

  it('커서와 검색어를 쿼리로 싣는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [], meta: {} }))
    await createApiVesselManagementProvider({ fetchImpl }).list({
      cursor: 'c2',
      search: 'STAR',
    })
    const [url] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('cursor=c2')
    expect(url).toContain('search=STAR')
  })

  it('목록 자리에 배열이 아닌 것이 오면 빈 목록으로 처리하지 않는다', async () => {
    // 「선박이 없다」와 「목록을 못 읽었다」는 사용자가 취할 행동이 다르다.
    const fetchImpl = vi.fn(async () => jsonResponse({ data: null }))
    await expect(createApiVesselManagementProvider({ fetchImpl }).list()).rejects.toThrow(
      MALFORMED_ERROR_MESSAGE,
    )
  })

  it('네트워크 실패는 안내 문구가 있는 오류가 된다', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('failed to fetch')
    })
    await expect(createApiVesselManagementProvider({ fetchImpl }).list()).rejects.toThrow(
      NETWORK_ERROR_MESSAGE,
    )
  })
})

describe('readPageMeta — 커서를 지어내지 않는다', () => {
  it('meta가 없으면 더 없음으로 읽는다', () => {
    expect(readPageMeta({ data: [] })).toEqual({ nextCursor: null, hasMore: false })
  })

  it('빈 문자열 커서는 커서가 아니다 — 같은 페이지를 무한히 다시 부른다', () => {
    expect(readPageMeta({ meta: { next_cursor: '', has_more: true } }).nextCursor).toBeNull()
  })

  it('has_more가 true가 아니면 false다', () => {
    expect(readPageMeta({ meta: { has_more: 'yes' } }).hasMore).toBe(false)
  })
})

describe('update — PATCH /vessels/{id}', () => {
  it('CSRF 헤더를 붙이고 본문을 싣는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: VESSEL }))
    await createApiVesselManagementProvider({ fetchImpl }).update('a1', { name: '새 이름' })

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${DEFAULT_API_BASE_URL}/vessels/a1`)
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ name: '새 이름' }))
    expect(init.headers).toHaveProperty('Content-Type', 'application/json')
  })

  it('200이지만 본문이 계약과 다르면 성공으로 처리하지 않는다', async () => {
    // 성공으로 두면 화면이 **저장되지 않은 값**을 저장된 것으로 보여 준다.
    const fetchImpl = vi.fn(async () => jsonResponse({ data: null }))
    await expect(
      createApiVesselManagementProvider({ fetchImpl }).update('a1', { name: 'x' }),
    ).rejects.toThrow(MALFORMED_ERROR_MESSAGE)
  })

  it('404는 NOT_FOUND로 옮긴다 — 목록을 다시 읽으라는 뜻이다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(errorBody('NOT_FOUND', '선박을 찾을 수 없습니다'), 404),
    )
    await expect(
      createApiVesselManagementProvider({ fetchImpl }).update('a1', { name: 'x' }),
    ).rejects.toMatchObject({ code: 'NOT_FOUND' })
  })

  it('서버가 지목한 필드를 그대로 옮긴다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(errorBody('VALIDATION_ERROR', '선종이 잘못됐습니다', 'ship_type'), 422),
    )
    await expect(
      createApiVesselManagementProvider({ fetchImpl }).update('a1', { ship_type: 'X' }),
    ).rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'ship_type' })
  })
})

describe('remove — DELETE /vessels/{id}', () => {
  it('200 + data.deleted 응답을 성공으로 받는다 (API_SPEC §2.5)', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: { deleted: true } }))
    await expect(
      createApiVesselManagementProvider({ fetchImpl }).remove('a1'),
    ).resolves.toBeUndefined()
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.method).toBe('DELETE')
  })

  it('오류 응답은 관리 오류로 옮긴다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(errorBody('INTERNAL_ERROR', '실패'), 500),
    )
    await expect(
      createApiVesselManagementProvider({ fetchImpl }).remove('a1'),
    ).rejects.toMatchObject({ code: 'MANAGEMENT_ERROR' })
  })
})

describe('toVesselManagementError — 알 수 없는 응답', () => {
  it('오류 객체가 없으면 상태 코드를 문구에 남긴다', () => {
    const error = toVesselManagementError(503, {})
    expect(error).toBeInstanceOf(VesselManagementError)
    expect(error.message).toContain('503')
  })
})
