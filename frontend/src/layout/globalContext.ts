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
): string | null {
  if (!isVesselScopedPath(pathname)) return null
  if (next.vesselId === null) return null
  if (next.voyageId !== null) return voyagePath(next.vesselId, next.voyageId)
  return vesselPath(next.vesselId)
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
