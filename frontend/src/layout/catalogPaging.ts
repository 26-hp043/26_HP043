/**
 * 선택기 카탈로그의 페이지 따라가기 (`#1073`).
 *
 * 상단바 항차 선택기(`layout/voyageCatalog.ts`)와 항차 CII 선박 선택기
 * (`features/voyage-cii/vesselCatalog.ts`)가 서버 기본 `limit` 20에서 잘려 **21번째 이후
 * 항목을 고를 수 없었다** — `#627`이 범위에 넣고 처리하지 않은 두 곳이다.
 *
 * 두 카탈로그가 같은 규칙으로 `meta.next_cursor`를 끝까지 따른다(`API_SPEC §2.1`·`§3.1`).
 * 한 페이지는 서버 상한(100)으로 받고, 상한 페이지 수를 두어 서버가 같은 커서를 되돌려 주는
 * 결함이 있어도 무한히 돌지 않는다.
 */

/** 서버 페이지 크기 상한 (`API_SPEC §1.5` — 최대 100). */
const PAGE_LIMIT = 100

/** 따라갈 최대 페이지 수 — 100 × 50 = 5,000건. 그 이상은 셀렉트가 아니라 검색 UI의 문제다. */
export const MAX_PAGES = 50

/** 응답 봉투에서 다음 커서를 읽는다. 없거나 빈 문자열이면 `null`(마지막 페이지). */
export function nextCursorOf(body: unknown): string | null {
  const next = (body as { meta?: { next_cursor?: unknown } } | null)?.meta?.next_cursor
  return typeof next === 'string' && next !== '' ? next : null
}

/** 커서·limit을 붙인 목록 URL. */
export function pagedUrl(base: string, cursor: string | null): string {
  const params = new URLSearchParams({ limit: String(PAGE_LIMIT) })
  if (cursor !== null) params.set('cursor', cursor)
  return `${base}?${params.toString()}`
}
