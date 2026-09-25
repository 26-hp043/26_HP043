/**
 * `/basemap/*`에 `Range`(`206`)를 채워 주는 Pages Function (`#1909`).
 *
 * Pages의 정적 자산 서버가 `Range`를 무시해 지도가 운영에서 **한 번도 뜨지 못했다**.
 * 경위·근거·대안 비교는 `functions/_byteRange.ts` 머리주석에 있다.
 *
 * `[[path]]`는 catch-all이라 `/basemap` 아래 모든 요청이 여기로 온다. **Range가 없는
 * 요청은 손대지 않고 그대로 흘린다** — 글리프(`fonts/*.pbf`)가 그 경로다.
 *
 * ⚠️ 조각을 만들려면 **자산 전체를 한 번 읽어야 한다**(상류가 부분 응답을 못 주므로).
 * 15 MB를 Worker 안에서 자르는 셈인데, 자산에는 `_headers`가 7일 캐시를 걸어 두어
 * `next()`가 엣지 캐시에서 온다. 캐시 API로 한 겹 더 쌓는 것은 **측정 전에는 넣지
 * 않는다** — 검증할 수 없는 부품을 늘리지 않기 위해서다.
 */

import { contentRangeValue, parseByteRange, unsatisfiedRangeValue } from '../_byteRange'

/** Pages Functions가 넘겨주는 문맥 — 이 함수가 쓰는 것만 적는다. */
interface AssetContext {
  request: Request
  /** 정적 자산 파이프라인. `Range`를 무시하고 **전체를 `200`으로** 준다. */
  next: () => Promise<Response>
}

/** 조각 응답에 옮기는 상류 헤더. 나머지(`content-length` 등)는 조각 기준으로 다시 쓴다. */
const COPIED_HEADERS = ['content-type', 'cache-control', 'etag', 'last-modified'] as const

function copyHeaders(from: Headers, to: Headers): void {
  for (const name of COPIED_HEADERS) {
    const value = from.get(name)
    if (value !== null) to.set(name, value)
  }
}

export async function onRequest(context: AssetContext): Promise<Response> {
  const { request, next } = context

  const upstream = await next()

  // 상류가 이미 부분 응답을 줬다면(장차 Pages가 byte serving을 지원하게 되면) 그대로
  // 흘린다 — 우리가 다시 자르면 **조각의 조각**이 된다.
  if (upstream.status !== 200) return upstream

  const rangeHeader = request.headers.get('Range')
  if (rangeHeader === null) {
    // 손대지 않되 **Range를 받는다는 사실은 알린다.** 상류에는 이 헤더가 없다.
    const headers = new Headers(upstream.headers)
    headers.set('Accept-Ranges', 'bytes')
    return new Response(upstream.body, { status: 200, headers })
  }

  const body = await upstream.arrayBuffer()
  const result = parseByteRange(rangeHeader, body.byteLength)

  if (result.kind === 'none') {
    const headers = new Headers(upstream.headers)
    headers.set('Accept-Ranges', 'bytes')
    return new Response(body, { status: 200, headers })
  }

  if (result.kind === 'unsatisfiable') {
    const headers = new Headers()
    copyHeaders(upstream.headers, headers)
    headers.set('Accept-Ranges', 'bytes')
    headers.set('Content-Range', unsatisfiedRangeValue(body.byteLength))
    return new Response(null, { status: 416, headers })
  }

  const { start, end } = result.range
  const slice = body.slice(start, end + 1)

  const headers = new Headers()
  copyHeaders(upstream.headers, headers)
  headers.set('Accept-Ranges', 'bytes')
  headers.set('Content-Range', contentRangeValue(result.range, body.byteLength))
  headers.set('Content-Length', String(slice.byteLength))
  return new Response(slice, { status: 206, headers })
}
