import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  VesselCatalogError,
  createApiVesselCatalog,
  createVesselCatalog,
} from './vesselCatalog'

/**
 * 선박 선택지 provider (#236).
 *
 * 이슈의 완료 기준을 그대로 옮긴다.
 *
 * * seed된 선박이 전부 나타난다
 * * 성공·실패 경로가 모두 테스트로 잠긴다
 */

const OK_BODY = {
  data: [
    { id: 'v-1', name: '샘플 벌크선', ship_type: 'BULK_CARRIER' },
    { id: 'v-2', name: '샘플 컨테이너선', ship_type: 'CONTAINER_SHIP' },
    { id: 'v-3', name: '샘플 일반화물선', ship_type: 'GENERAL_CARGO' },
  ],
}

function mockFetch(impl: (...args: unknown[]) => Promise<unknown> | unknown) {
  const spy = vi.fn(impl)
  vi.stubGlobal('fetch', spy)
  return spy
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})


describe('실 API 카탈로그', () => {
  it('seed된 선박을 전부 돌려준다 — 고정표 1척 제약이 사라진다', async () => {
    mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createApiVesselCatalog('/api/v1').listVessels()

    expect(rows).toHaveLength(3)
    expect(rows.map((r) => r.displayName)).toEqual([
      '샘플 벌크선',
      '샘플 컨테이너선',
      '샘플 일반화물선',
    ])
  })

  it('GET /vessels를 인증 헤더와 함께 부른다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    await createApiVesselCatalog('/api/v1').listVessels()

    expect(spy).toHaveBeenCalledTimes(1)
    const [url, init] = spy.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/vessels')
    expect(init.method).toBe('GET')
    expect(init.credentials).toBe('include')
  })

  it('네트워크 실패를 VesselCatalogError로 옮기고 원인을 보존한다', async () => {
    const cause = new TypeError('Failed to fetch')
    mockFetch(() => Promise.reject(cause))

    const promise = createApiVesselCatalog('/api/v1').listVessels()

    await expect(promise).rejects.toBeInstanceOf(VesselCatalogError)
    await expect(promise).rejects.toMatchObject({ cause })
  })

  it('5xx는 목록 실패로 옮긴다', async () => {
    mockFetch(() => jsonResponse({}, 500))

    await expect(createApiVesselCatalog('/api/v1').listVessels()).rejects.toBeInstanceOf(
      VesselCatalogError,
    )
  })

  it('JSON이 깨져도 화면에는 VesselCatalogError만 나간다', async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token')
      },
    }))

    await expect(createApiVesselCatalog('/api/v1').listVessels()).rejects.toBeInstanceOf(
      VesselCatalogError,
    )
  })

  it('data가 배열이 아니면 빈 목록으로 둔다 — 예외로 만들지 않는다', async () => {
    mockFetch(() => jsonResponse({ data: null }))

    await expect(createApiVesselCatalog('/api/v1').listVessels()).resolves.toEqual([])
  })

  it('id·name이 없는 행은 건너뛴다', async () => {
    mockFetch(() =>
      jsonResponse({ data: [{ id: 'v-1', name: '정상' }, { id: 'v-2' }, { name: '이름만' }] }),
    )

    const rows = await createApiVesselCatalog('/api/v1').listVessels()

    expect(rows.map((r) => r.id)).toEqual(['v-1'])
  })
})

describe('전환 규칙', () => {
  it('환경과 무관하게 서버를 부른다 — 갈래가 없다 (#542)', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    await createVesselCatalog({} as ImportMetaEnv).listVessels()

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('서버를 부른다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createVesselCatalog({} as ImportMetaEnv).listVessels()

    expect(spy).toHaveBeenCalled()
    expect(rows).toHaveLength(3)
  })

})
