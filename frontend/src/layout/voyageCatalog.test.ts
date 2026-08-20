import { describe, expect, it, vi } from 'vitest'
import {
  VoyageCatalogError,
  createApiVoyageCatalog,
  createVoyageCatalog,
  voyageDisplayName,
} from './voyageCatalog'

/**
 * #512 — 항차 선택지 provider.
 *
 * `vesselCatalog.ts`(#236)와 같은 경계다 — 화면은 출처를 알지 않고, 조회 경로
 * 전환은 같은 환경변수로 결정된다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('voyageDisplayName — 여러 건이 같은 문자열이 되지 않게 한다', () => {
  it('항차 번호가 있으면 그것이 이름이다', () => {
    expect(voyageDisplayName({ voyage_no: 'V-2026-001' })).toBe('V-2026-001')
  })

  it('번호가 없으면 구간으로 대신한다', () => {
    expect(
      voyageDisplayName({ departure_port_name: '부산', arrival_port_name: '싱가포르' }),
    ).toBe('부산 → 싱가포르')
  })

  it('한쪽 항구만 있으면 나머지를 —로 둔다', () => {
    expect(voyageDisplayName({ departure_port_name: '부산' })).toBe('부산 → —')
  })

  it('둘 다 없으면 id 앞자리를 보인다 — 「이름 없는 항차」로 뭉뚱그리지 않는다', () => {
    expect(voyageDisplayName({ id: '0123456789abcdef' })).toBe('01234567')
  })

  it('빈 문자열 항차 번호는 번호가 아니다', () => {
    expect(voyageDisplayName({ voyage_no: '   ', departure_port_name: '부산' })).toBe(
      '부산 → —',
    )
  })
})


describe('실 API — GET /vessels/{id}/voyages', () => {
  it('선박 id를 경로에 넣어 부른다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)
    await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    const [url] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vessels/v1/voyages')
    vi.unstubAllGlobals()
  })

  it('id가 없는 행은 버린다 — 고를 수 없는 선택지다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: [{ voyage_no: 'V-1' }, { id: 'a', voyage_no: 'V-2' }] }),
    )
    vi.stubGlobal('fetch', fetchImpl)
    const options = await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    expect(options).toEqual([{ id: 'a', displayName: 'V-2', status: '' }])
    vi.unstubAllGlobals()
  })

  it('data가 배열이 아니면 빈 목록으로 본다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ data: null })))
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).resolves.toEqual([])
    vi.unstubAllGlobals()
  })

  it('오류 응답은 VoyageCatalogError가 된다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 500)))
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).rejects.toBeInstanceOf(
      VoyageCatalogError,
    )
    vi.unstubAllGlobals()
  })

  it('네트워크 실패도 VoyageCatalogError가 된다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('failed to fetch')
      }),
    )
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).rejects.toBeInstanceOf(
      VoyageCatalogError,
    )
    vi.unstubAllGlobals()
  })
})

describe('createVoyageCatalog', () => {
  it('환경과 무관하게 실 API를 부른다 — 갈래가 없다 (#542)', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)

    await createVoyageCatalog({} as ImportMetaEnv).listVoyages('v1')

    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('true면 실 API를 부른다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)
    await createVoyageCatalog({} as ImportMetaEnv).listVoyages(
      'v1',
    )
    expect(fetchImpl).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
