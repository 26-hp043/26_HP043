import { describe, expect, it } from 'vitest'
import { onRequest as apiHeaders } from './api/_middleware'
import { onRequest as basemapHeaders } from './basemap/_middleware'
import { onRequest as api } from './api/[[path]]'
import { onRequest as basemap } from './basemap/[[path]]'

const expected = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
}
function assertHeaders(response: Response) {
  for (const [name, value] of Object.entries(expected)) expect(response.headers.get(name)).toBe(value)
}

describe('Function 보안 헤더 (#2111)', () => {
  it('API 자체의 설정 오류 502에도 붙인다', async () => {
    const response = await apiHeaders({ next: () => api({
      request: new Request('https://pages.example/api/v1/health'), env: {},
    }) })
    expect(response.status).toBe(502)
    assertHeaders(response)
    expect((await response.json()).error.code).toBe('PROXY_NOT_CONFIGURED')
  })

  it.each([200, 401, 405, 429, 500])('상류 %i 응답의 본문·쿠키·캐시를 보존한다', async (status) => {
    const headers = new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
    headers.append('Set-Cookie', 'sid=test-session; HttpOnly')
    headers.append('Set-Cookie', 'csrf=test-csrf')
    const upstream = new Response('{"data":{}}', { status, headers })
    const response = await apiHeaders({ next: async () => upstream })
    expect(response.status).toBe(status)
    assertHeaders(response)
    expect(response.headers.get('content-type')).toBe('application/json')
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(response.headers.getSetCookie()).toEqual(headers.getSetCookie())
    expect(await response.text()).toBe('{"data":{}}')
  })

  it.each([['bytes=1-2', 206], ['bytes=999-', 416], [null, 200]] as const)(
    '지도 Range %s → %i의 상태·범위·본문을 보존한다', async (range, status) => {
      const request = new Request('https://pages.example/basemap/world.pmtiles', {
        headers: range === null ? {} : { Range: range },
      })
      const response = await basemapHeaders({ next: () => basemap({ request, next: async () =>
        new Response(new Uint8Array([0, 1, 2, 3]), {
          headers: { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'public, max-age=604800' },
        }),
      }) })
      expect(response.status).toBe(status)
      assertHeaders(response)
      expect(response.headers.get('cache-control')).toBe('public, max-age=604800')
      if (status === 206) {
        expect(response.headers.get('content-range')).toBe('bytes 1-2/4')
        expect(response.headers.get('content-length')).toBe('2')
        expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([1, 2]))
      } else if (status === 416) {
        expect(response.headers.get('content-range')).toBe('bytes */4')
        expect(await response.text()).toBe('')
      } else expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([0, 1, 2, 3]))
    },
  )
})
