// @vitest-environment jsdom
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  fetchSeaRoute,
  seaRouteKey,
  useSeaRoutes,
  type SeaRouteLine,
  type SeaRouteRequest,
} from './seaRoute'

/**
 * 해상 경로망 조회 (`#1300` · `API_SPEC §3.11`).
 *
 * 잠그는 것은 셋이다 — ⑴ 질의가 계약대로 나간다(경유지는 둘 다 있을 때만) ⑵ 계약과 다른
 * 응답은 「못 받았다」이지 선이 아니다(지어내지 않는다) ⑶ 훅이 같은 질문을 두 번 묻지
 * 않고 실패를 실패로 남긴다.
 */

const BUSAN_TO_SINGAPORE: SeaRouteRequest = {
  fromLat: 35.1,
  fromLon: 129.0333,
  toLat: 1.2833,
  toLon: 103.85,
}
const LINE = {
  data: {
    coordinates: [
      [129.0333, 35.1],
      [129.2, 35],
      [103.85, 1.2833],
    ],
    length_nm: 2552.14,
    legs: 1,
    source: 'searoute/marnet',
  },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

describe('fetchSeaRoute — 질의와 응답 계약', () => {
  it('두 점을 계약 이름으로 보내고 좌표 목록을 받는다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(LINE))

    const line = await fetchSeaRoute(BUSAN_TO_SINGAPORE, fetchImpl, '/api/v1')

    const url = String(fetchImpl.mock.calls[0][0])
    expect(url).toContain('/api/v1/ports/sea-route?')
    expect(url).toContain('from_lat=35.1')
    expect(url).toContain('to_lon=103.85')
    expect(url).not.toContain('via_')
    expect(line).toEqual<SeaRouteLine>({
      coordinates: [
        [129.0333, 35.1],
        [129.2, 35],
        [103.85, 1.2833],
      ],
      source: {
        id: 'searoute/marnet',
        label: 'Eurostat SeaRoute 해상 경로망',
        attribution: '해상 경로망 © Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)',
        license: 'Eurostat SeaRoute: EUPL-1.2; searoute: Apache-2.0',
        sourceUrl: 'https://github.com/eurostat/searoute',
        displayOnly: true,
      },
      lengthNm: 2552.14,
      legs: 1,
    })
  })

  it('경유지가 있으면 via 둘을 함께 보낸다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse({ data: { ...LINE.data, legs: 2 } }))

    await fetchSeaRoute({ ...BUSAN_TO_SINGAPORE, via: { lat: 21.3, lon: -157.87 } }, fetchImpl)

    const url = String(fetchImpl.mock.calls[0][0])
    expect(url).toContain('via_lat=21.3')
    expect(url).toContain('via_lon=-157.87')
  })

  it('실패 응답은 던진다 — 선을 지어내지 않는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ error: {} }, 500))
    await expect(fetchSeaRoute(BUSAN_TO_SINGAPORE, fetchImpl)).rejects.toThrow(/500/)
  })

  it.each([
    ['좌표가 없다', { data: { length_nm: 1, legs: 1 } }],
    ['좌표 쌍이 아니다', { data: { coordinates: [[1]], length_nm: 1, legs: 1 } }],
    ['좌표가 문자열이다', { data: { coordinates: [['1', '2']], length_nm: 1, legs: 1 } }],
    ['길이가 문자열이다', { data: { coordinates: [], length_nm: '1', legs: 1 } }],
    ['출처가 없다', { data: { coordinates: [[0, 0], [1, 1]], length_nm: 1, legs: 1 } }],
    ['알 수 없는 출처다', { data: { ...LINE.data, source: 'server/free-text' } }],
    ['data가 없다', {}],
  ])('계약과 다른 응답(%s)은 던진다', async (_name, body) => {
    const fetchImpl = vi.fn(async () => jsonResponse(body))
    await expect(fetchSeaRoute(BUSAN_TO_SINGAPORE, fetchImpl)).rejects.toThrow(/계약/)
  })
})

describe('seaRouteKey', () => {
  it('경유지가 다르면 다른 열쇠, 같으면 같은 열쇠다', () => {
    const plain = seaRouteKey(BUSAN_TO_SINGAPORE)
    expect(seaRouteKey({ ...BUSAN_TO_SINGAPORE })).toBe(plain)
    expect(seaRouteKey({ ...BUSAN_TO_SINGAPORE, via: null })).toBe(plain)
    expect(seaRouteKey({ ...BUSAN_TO_SINGAPORE, via: { lat: 21.3, lon: -157.87 } })).not.toBe(plain)
  })
})

describe('useSeaRoutes', () => {
  it('같은 질문은 한 번만 묻고, 받은 선과 실패를 열쇠로 돌려준다', async () => {
    const failing: SeaRouteRequest = { ...BUSAN_TO_SINGAPORE, toLat: 51.9 }
    const fetchImpl = vi.fn(async (input: unknown) =>
      String(input).includes('to_lat=51.9') ? jsonResponse({}, 500) : jsonResponse(LINE),
    )
    const requests = [BUSAN_TO_SINGAPORE, { ...BUSAN_TO_SINGAPORE }, failing]

    const { result } = renderHook(() => useSeaRoutes(requests, fetchImpl))

    await waitFor(() => {
      expect(Object.keys(result.current)).toHaveLength(2)
    })
    expect(result.current[seaRouteKey(BUSAN_TO_SINGAPORE)]).toMatchObject({ legs: 1 })
    expect(result.current[seaRouteKey(failing)]).toBe('failed')
    // 같은 열쇠 둘 + 다른 열쇠 하나 = 요청 둘.
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('재시도 신호가 바뀌면 실패한 열쇠만 다시 묻는다 — 받은 선은 다시 묻지 않는다 (#1856)', async () => {
    const failing: SeaRouteRequest = { ...BUSAN_TO_SINGAPORE, toLat: 51.9 }
    let healthy = false
    const fetchImpl = vi.fn(async (input: unknown) =>
      String(input).includes('to_lat=51.9') && !healthy ? jsonResponse({}, 500) : jsonResponse(LINE),
    )
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const requests = [BUSAN_TO_SINGAPORE, failing]

    const { result, rerender } = renderHook(
      ({ token, list }: { token: number; list: SeaRouteRequest[] }) =>
        useSeaRoutes(list, fetchImpl, token),
      { initialProps: { token: 0, list: requests } },
    )
    await waitFor(() => expect(result.current[seaRouteKey(failing)]).toBe('failed'))
    expect(fetchImpl).toHaveBeenCalledTimes(2)

    // 목록만 바뀌면(같은 신호) 실패를 다시 묻지 않는다 — 종전의 폭주 방지.
    rerender({ token: 0, list: [...requests] })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetchImpl).toHaveBeenCalledTimes(2)

    healthy = true
    rerender({ token: 1, list: requests })
    await waitFor(() => expect(result.current[seaRouteKey(failing)]).toMatchObject({ legs: 1 }))
    expect(fetchImpl).toHaveBeenCalledTimes(3)
    const urls = fetchImpl.mock.calls.map(([input]) => String(input))
    expect(urls.filter((url) => url.includes('to_lat=51.9'))).toHaveLength(2)
    expect(urls.filter((url) => url.includes('to_lat=1.2833'))).toHaveLength(1)
  })
})
