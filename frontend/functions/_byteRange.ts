/**
 * Cloudflare Pages Functions — `Range` 요청의 순수 부분 (`#1909`).
 *
 * ## 왜 우리가 Range를 채워야 하는가
 *
 * 지도 타일은 **PMTiles 아카이브 파일 하나**다(`features/fleet/basemap.ts` · `#985`).
 * PMTiles는 그 한 파일에서 **필요한 조각만 Range 요청으로 읽는다** — 헤더 16 KiB,
 * 디렉터리, 그리고 타일마다 수 KiB다.
 *
 * **Cloudflare Pages의 정적 자산 서버는 `Range`를 무시한다.** 실측(2026-09-25):
 *
 * ```
 * curl -H 'Range: bytes=0-6' …/basemap/bluelog.pmtiles
 * → HTTP/2 200 · content-length: 15017319 · accept-ranges 없음
 * ```
 *
 * `/favicon.svg`·`/assets/*.js`도 같다 — 파일 크기나 종류의 문제가 아니라 **Pages가
 * byte serving을 하지 않는다.** 그래서 두 곳이 함께 막혔다.
 *
 * ⑴ `pmtiles`가 **예외를 던진다** — 라이브러리가 `200`에 요청보다 큰 `Content-Length`가
 *    실려 오면 `Server returned no content-length header or content-length exceeding
 *    request. Check that your storage backend supports HTTP Byte Serving.`로 멈춘다.
 * ⑵ `hasBasemap()`이 **`206`이 아니면 「자산 없음」으로 접는다**(`#1144`의 판정). 그래서
 *    운영 화면은 지도를 그리지 않고 **개략도로 떨어졌다** — 고장이 조용해서, 화면만
 *    보면 「지도가 예전 그대로」로 보인다.
 *
 * ⑵는 옳은 판정이다. Range가 없으면 ⑴ 때문에 어차피 지도가 뜨지 않으니, 회색 사각형
 * 대신 개략도로 접는 쪽이 낫다(`#1144`). **고칠 곳은 판정이 아니라 서빙이다.**
 *
 * ## 왜 자산 형식을 바꾸지 않는가
 *
 * 타일을 `{z}/{x}/{y}` 파일 수천 개로 풀면 Range가 필요 없어진다. 그러나 `#985`가
 * 「파일 하나 · 26 MB · 커밋한다」를 자산 규격으로 정했고, 그 결정과 거기 딸린 문서·
 * 스크립트·테스트를 함께 바꾸는 일이다. **서빙 한 겹으로 닫히는 문제에 자산 규격을
 * 건드리지 않는다.** 글리프(`/basemap/fonts/*.pbf`)는 이미 파일 하나씩이라 Range와
 * 무관하고, 이 파일도 그 요청은 그대로 흘린다.
 *
 * ## 이 파일이 라우트가 아닌 이유
 *
 * `_`로 시작하는 파일은 Pages Functions의 **라우트로 등록되지 않는다**(`_proxy.ts`와
 * 같은 이유). 해석·계산만 두어 `_byteRange.test.ts`가 Worker 런타임 없이 검사한다.
 */

/** 바이트 구간 — 양끝을 포함한다(HTTP `Range`의 셈법). */
export interface ByteRange {
  readonly start: number
  readonly end: number
}

/**
 * `Range` 헤더 해석 결과.
 *
 * - `none` — 헤더가 없거나 우리가 다루지 않는 형태다. **전체를 `200`으로 준다.**
 *   RFC 9110 §14.2가 「서버는 Range를 무시해도 된다」로 적으므로 규격 위반이 아니다.
 * - `satisfiable` — 구간이 파일 안에 있다. `206`으로 그 조각만 준다.
 * - `unsatisfiable` — 시작이 파일 끝을 넘었다. `416`으로 답한다(`pmtiles`는 이때
 *   `Content-Range: bytes * /크기`를 읽어 다시 묻는다).
 */
export type ByteRangeResult =
  | { readonly kind: 'none' }
  | { readonly kind: 'satisfiable'; readonly range: ByteRange }
  | { readonly kind: 'unsatisfiable' }

/** 정수만 받는다 — `bytes=1.5-2`·`bytes=+1-2` 같은 값을 숫자로 삼지 않기 위해서다. */
function parseIndex(value: string): number | null {
  if (!/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

/**
 * `Range` 헤더를 구간 하나로 해석한다.
 *
 * 다루는 형태는 셋이다 — `bytes=0-6`(양끝) · `bytes=100-`(끝까지) · `bytes=-500`(마지막
 * 500바이트). **구간을 여럿 적은 요청(`bytes=0-1,5-6`)은 `none`으로 접는다** —
 * 여러 조각 응답(`multipart/byteranges`)을 만들 이유가 없다. `pmtiles`는 한 구간만 쓴다.
 */
export function parseByteRange(header: string | null, size: number): ByteRangeResult {
  if (header === null || size <= 0) return { kind: 'none' }

  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim())
  if (match === null) return { kind: 'none' }

  const [, rawStart, rawEnd] = match

  // `bytes=-500` — 마지막 500바이트. 파일보다 크게 적었으면 **전체**다(RFC 9110 §14.1.2).
  if (rawStart === '') {
    const suffix = parseIndex(rawEnd)
    if (suffix === null || suffix === 0) return { kind: 'none' }
    return { kind: 'satisfiable', range: { start: Math.max(0, size - suffix), end: size - 1 } }
  }

  const start = parseIndex(rawStart)
  if (start === null) return { kind: 'none' }
  // 시작이 파일 끝을 넘으면 만족시킬 수 없다 — 전체를 주면 `pmtiles`가 다시 멈춘다.
  if (start >= size) return { kind: 'unsatisfiable' }

  // `bytes=100-` — 끝까지.
  if (rawEnd === '') return { kind: 'satisfiable', range: { start, end: size - 1 } }

  const end = parseIndex(rawEnd)
  if (end === null || end < start) return { kind: 'none' }
  // 끝을 파일 밖으로 적는 것은 허용된다 — 있는 데까지 준다.
  return { kind: 'satisfiable', range: { start, end: Math.min(end, size - 1) } }
}

/** `206`의 `Content-Range` 값. */
export function contentRangeValue(range: ByteRange, size: number): string {
  return `bytes ${range.start}-${range.end}/${size}`
}

/** `416`의 `Content-Range` 값 — 크기만 알려 준다. */
export function unsatisfiedRangeValue(size: number): string {
  return `bytes */${size}`
}
