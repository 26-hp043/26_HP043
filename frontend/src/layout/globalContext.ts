import { matchPath } from 'react-router'
import { SCREEN_BY_ID } from '../screens'

/**
 * 상단바 전역 컨텍스트(선박·항차)의 규칙 (#512).
 *
 * ## 정본은 URL이다
 *
 * 이 앱에는 선박 범위를 이미 표현하는 것이 있다 — 라우트다. `#348`이
 * `/vessels/:vesselId`·`/vessels/:vesselId/voyages/:voyageId`로 계층 드릴다운을
 * 만들었고, 선박 상세·실시간 CII는 그 경로 파라미터로 대상을 정한다.
 *
 * 그래서 상단바가 **별도의 선택 상태를 소유하지 않는다.** 소유하면 두 곳이 갈리고,
 * 갈렸을 때 어느 쪽이 맞는지 화면을 봐서는 알 수 없다 — `#236`이 고친 것이 정확히
 * 그 형태였다(계산은 서버로 가는데 선택지는 고정표에서 왔다).
 *
 * **상단바는 URL을 읽고 URL을 바꾼다.**
 *
 * - 계층 화면에 있으면 → 경로에서 읽은 것이 곧 선택 상태다
 * - 계층 밖 화면(대시보드·보고서 등)에 있으면 → 마지막 선택을 **기억해 둔 것**을 보인다
 * - 선택을 바꾸면 → 그 대상의 화면으로 이동한다
 *
 * ## 왜 기억이 따로 필요한가
 *
 * 완료 기준이 「선택이 화면 전환 후에도 유지된다」이다. 대시보드처럼 경로에
 * 선박이 없는 화면으로 가면 URL만으로는 선택이 사라진다. 그래서 마지막 선택을
 * `sessionStorage`에 남긴다 — `localStorage`가 아닌 이유는 **탭마다 다른 배를 보는
 * 것이 정상적인 사용 방식**이고, 로그아웃 뒤 다른 계정으로 들어왔을 때 남의 선택이
 * 남아 있으면 안 되기 때문이다.
 */

/** 전역 컨텍스트 값. 선택하지 않았으면 `null`. */
export interface GlobalContextValue {
  vesselId: string | null
  voyageId: string | null
}

export const EMPTY_CONTEXT: GlobalContextValue = { vesselId: null, voyageId: null }

/** `sessionStorage` 키. 다른 저장값과 섞이지 않도록 접두를 붙인다. */
export const STORAGE_KEY = 'bluelog.globalContext'

/**
 * 쿼리 파라미터 이름 (#484 B안).
 *
 * **API 필드명과 같은 표기를 쓴다** — `vessel_id`·`voyage_id`. 주소창에 보이는
 * 값이라 화면 라벨처럼 보일 수 있으나, 이 값은 사람이 읽는 라벨이 아니라
 * 식별자이며 `#513`(데이터 점검)이 `?vessel_id=&severity=`로 쓰기로 한 형식과
 * 맞춘다. 두 화면이 다른 이름을 쓰면 링크를 옮겨 붙일 때 조용히 무시된다.
 */
export const VESSEL_QUERY_KEY = 'vessel_id'
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
const VOYAGE_QUERY_KEY = 'voyage_id'

/**
 * 컨텍스트를 **쿼리로 담는 화면들** (#484 B안).
 *
 * ## 왜 경로가 아니라 쿼리인가
 *
 * 이 셋은 계층에 속하지만(`UIFLOW §2` — 2-3은 선박, 2-1·2-2는 항차) 경로는
 * 평면이다. 경로를 계층형으로 옮기는 A안도 검토했으나 두 가지에 걸린다.
 *
 * 1. **사이드바에서 링크할 수 없게 된다.** 경로에 `:vesselId`가 들어가면
 *    `screens.ts`의 `NAV_ORDER`에 둘 수 없다 — 이미 계층 경로를 가진
 *    `VESSEL_DETAIL`·`REALTIME_CII`가 `OFF_NAV_ORDER`에 있는 이유가 그것이다.
 *    세 화면을 사이드바에서 빼려면 `UIFLOW` 개정이 선행된다.
 * 2. **`#511`이 방금 고친 것을 되돌린다.** 「선박 미선택 상태에서 에러 대신
 *    입력 UI가 보인다」가 그 이슈의 완료 기준인데, 계층 경로는 선박 없이는
 *    진입 자체를 막는다.
 *
 * 쿼리는 둘 다 건드리지 않으면서 **새로고침·링크 공유에서 선택이 살아남게**
 * 한다. 그것이 `#535`가 요구한 것이고 `sessionStorage` 기억만으로는 안 되는
 * 부분이다.
 */
const QUERY_CONTEXT_PATHS: readonly string[] = [
  SCREEN_BY_ID.ANNUAL_GRADE.path,
  SCREEN_BY_ID.CII_FORECAST.path,
  SCREEN_BY_ID.ROUTE_COMPARISON.path,
]

/** 지금 경로가 선박 범위를 **쿼리로** 표현하는 화면인가. */
export function isVesselQueryPath(pathname: string): boolean {
  return QUERY_CONTEXT_PATHS.some((path) => matchPath(path, pathname) !== null)
}

/**
 * 쿼리스트링에서 선박·항차를 읽는다.
 *
 * **값이 빈 문자열이면 없는 것으로 본다.** `?vessel_id=`처럼 키만 남은 주소는
 * 사용자가 선택을 지운 결과이거나 링크가 잘린 것이며, 둘 다 「빈 문자열인 선박」이
 * 아니다. 지어내지 않는다 — `loadStored()`와 같은 규칙이다.
 */
export function readFromQuery(search: string): GlobalContextValue {
  const params = new URLSearchParams(search)
  const vesselId = params.get(VESSEL_QUERY_KEY)
  const voyageId = params.get(VOYAGE_QUERY_KEY)
  return {
    vesselId: vesselId ? vesselId : null,
    // 선박이 없으면 항차도 없다 — `selectVessel`이 지키는 규칙과 같다.
    voyageId: vesselId && voyageId ? voyageId : null,
  }
}

/**
 * 컨텍스트를 쿼리에 실은 주소를 만든다.
 *
 * **다른 쿼리 파라미터는 보존한다.** `#513`이 데이터 점검에 `severity`를 함께
 * 쓰기로 했고, 그 화면에서 선박을 바꿨다고 필터가 사라지면 안 된다.
 */
export function withContextQuery(
  pathname: string,
  search: string,
  value: GlobalContextValue,
): string {
  const params = new URLSearchParams(search)
  if (value.vesselId === null) params.delete(VESSEL_QUERY_KEY)
  else params.set(VESSEL_QUERY_KEY, value.vesselId)
  if (value.vesselId === null || value.voyageId === null) params.delete(VOYAGE_QUERY_KEY)
  else params.set(VOYAGE_QUERY_KEY, value.voyageId)
  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}

/**
 * 경로에서 선박·항차를 읽는다. 계층 화면이 아니면 둘 다 `null`.
 *
 * `screens.ts`의 경로 상수를 쓴다 — 문자열을 다시 적으면 `#348`이 경로를 바꿀 때
 * 이 파일만 낡는다.
 */
export function readFromPath(pathname: string): GlobalContextValue {
  const voyage = matchPath(SCREEN_BY_ID.REALTIME_CII.path, pathname)
  if (voyage) {
    return {
      vesselId: voyage.params.vesselId ?? null,
      voyageId: voyage.params.voyageId ?? null,
    }
  }
  const vessel = matchPath(SCREEN_BY_ID.VESSEL_DETAIL.path, pathname)
  if (vessel) {
    return { vesselId: vessel.params.vesselId ?? null, voyageId: null }
  }
  return EMPTY_CONTEXT
}

/** 지금 경로가 선박 범위를 URL로 표현하는 화면인가. */
export function isVesselScopedPath(pathname: string): boolean {
  return (
    matchPath(SCREEN_BY_ID.VESSEL_DETAIL.path, pathname) !== null ||
    matchPath(SCREEN_BY_ID.REALTIME_CII.path, pathname) !== null
  )
}

/** 선박 상세 경로. */
export function vesselPath(vesselId: string): string {
  return SCREEN_BY_ID.VESSEL_DETAIL.path.replace(':vesselId', vesselId)
}

/** 실시간 CII 경로. */
export function voyagePath(vesselId: string, voyageId: string): string {
  return SCREEN_BY_ID.REALTIME_CII.path.replace(':vesselId', vesselId).replace(
    ':voyageId',
    voyageId,
  )
}

/**
 * 선택을 바꿨을 때 이동할 경로. 이동할 필요가 없으면 `null`.
 *
 * **계층 밖 화면에서는 이동시키지 않는다.** 대시보드를 보다가 상단에서 배를 골랐다고
 * 화면이 튀면 사용자가 하려던 일이 끊긴다 — 고른 것은 기억해 두고, 계층 화면으로
 * 들어갈 때 그 선택이 쓰인다.
 */
export function navigationFor(
  pathname: string,
  next: GlobalContextValue,
  search = '',
): string | null {
  // 쿼리로 담는 화면은 **머무른 채 주소만 갱신한다** (#484 B안). 이동시키면
  // 계층 화면과 같은 문제가 생긴다 — 조건을 입력하던 중 화면이 튄다.
  if (isVesselQueryPath(pathname)) {
    const target = withContextQuery(pathname, search, next)
    return target === `${pathname}${search}` ? null : target
  }
  if (!isVesselScopedPath(pathname)) return null
  if (next.vesselId === null) return null
  if (next.voyageId !== null) return voyagePath(next.vesselId, next.voyageId)
  return vesselPath(next.vesselId)
}

/**
 * 지금 화면에서 **유효한 선택**. 어느 쪽이 이기는지 한 줄로 정한다.
 *
 * | 화면 | 정본 |
 * |---|---|
 * | 계층 경로 (`/vessels/:vesselId…`) | 경로 |
 * | 쿼리 화면 (`/voyage-cii` 등) | 쿼리 — **단 비어 있으면 기억해 둔 값** |
 * | 그 밖 (대시보드·보고서) | 기억해 둔 값 |
 *
 * 쿼리가 비었을 때 기억으로 내려가는 것이 중요하다. 사이드바에서 「CII 예측」을
 * 누르면 쿼리 없는 주소로 들어오는데, 그때 선택이 초기화되면 상단바와 화면이
 * 다시 갈린다 — `#535`가 지적한 그 상태다.
 */
export function readContext(
  pathname: string,
  search: string,
  remembered: GlobalContextValue,
): GlobalContextValue {
  if (isVesselScopedPath(pathname)) return readFromPath(pathname)
  if (isVesselQueryPath(pathname)) {
    const fromQuery = readFromQuery(search)
    return fromQuery.vesselId === null ? remembered : fromQuery
  }
  return remembered
}

/**
 * 선박을 바꾸면 항차 선택은 버린다.
 *
 * 항차는 선박에 매달려 있다(`GET /vessels/{id}/voyages`). 배를 바꿨는데 항차가
 * 남아 있으면 **다른 배의 항차를 가리키는 조합**이 만들어지고, 그 조합으로 만든
 * 경로는 404가 난다.
 */
export function selectVessel(
  current: GlobalContextValue,
  vesselId: string | null,
): GlobalContextValue {
  if (vesselId === current.vesselId) return current
  return { vesselId, voyageId: null }
}

/** 항차만 바꾼다. 선박이 없으면 항차도 고를 수 없다. */
export function selectVoyage(
  current: GlobalContextValue,
  voyageId: string | null,
): GlobalContextValue {
  if (current.vesselId === null) return current
  return { ...current, voyageId }
}

/** 저장된 선택을 읽는다. 형태가 다르면 없는 것으로 본다 — 지어내지 않는다. */
export function loadStored(storage: Storage | undefined = safeSessionStorage()): GlobalContextValue {
  if (!storage) return EMPTY_CONTEXT
  let raw: string | null
  try {
    raw = storage.getItem(STORAGE_KEY)
  } catch {
    return EMPTY_CONTEXT
  }
  if (raw === null) return EMPTY_CONTEXT
  try {
    const parsed = JSON.parse(raw) as Partial<GlobalContextValue>
    return {
      vesselId: typeof parsed.vesselId === 'string' ? parsed.vesselId : null,
      voyageId: typeof parsed.voyageId === 'string' ? parsed.voyageId : null,
    }
  } catch {
    return EMPTY_CONTEXT
  }
}

/** 선택을 저장한다. 저장에 실패해도 화면은 계속 돈다 — 편의 기능이다. */
export function saveStored(
  value: GlobalContextValue,
  storage: Storage | undefined = safeSessionStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    /* 저장 실패는 무시한다 — 사생활 보호 모드·용량 초과 등. */
  }
}

/** SSR·테스트 환경에 `sessionStorage`가 없을 수 있다. */
function safeSessionStorage(): Storage | undefined {
  try {
    return globalThis.sessionStorage
  } catch {
    return undefined
  }
}

/**
 * 화면에 보일 선박 이름. 목록에 없으면 **id를 감추지 않고 그대로 보인다.**
 *
 * 「알 수 없는 선박」으로 뭉뚱그리면 사용자가 무엇을 고른 상태인지 알 수 없고,
 * 목록이 아직 안 왔을 때와 삭제된 배일 때가 구분되지 않는다.
 */
export function displayName(
  options: ReadonlyArray<{ id: string; displayName: string }>,
  id: string | null,
): string | null {
  if (id === null) return null
  return options.find((option) => option.id === id)?.displayName ?? id
}
