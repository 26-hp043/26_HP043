import { useEffect, useRef, useState } from 'react'
import { DEFAULT_API_BASE_URL } from '../../api/base'

/**
 * 공개 해상 경로망 위의 바닷길 (`#1300` · `API_SPEC §3.11`).
 *
 * ## 선은 서버가 만든다
 *
 * 경로망(Eurostat SeaRoute · EUPL-1.2)은 서버의 `searoute` 패키지가 갖고 있고, 화면은
 * 두 점(경유지가 있으면 세 점)을 보내 좌표 목록을 받는다. **거리 추정(`§3.9`)과 같은
 * 원칙**이다 — 화면에 경로망을 두면 두 벌이 되고, 10MB 데이터를 브라우저에 내리게 된다.
 *
 * ## 표시용이다
 *
 * 응답의 `length_nm`은 선의 길이일 뿐 **표의 거리가 아니다.** 계산 거리는 사용자 입력
 * 또는 대권거리다(`PRD §15.2`). 그래서 이 파일은 길이를 화면에 올리지 않는다 — 받되
 * 쓰지 않는 값을 두는 이유는 응답 계약(`§3.11`)을 그대로 검사하기 위해서다.
 *
 * ## 못 받으면 선을 지어내지 않는다
 *
 * 종전 대권선으로 되돌리지 않는다. 캡션이 「경로망 위의 경로」라고 말하는 자리에 육지를
 * 가로지르는 최단 경로를 그리면 **캡션이 거짓이 된다.** 실패한 선은 비우고 그 사실을
 * 지도 옆에 적는다(`FleetMap`).
 */

/** 서버에 묻는 두 점(+경유지). 좌표는 숫자다 — 지도가 숫자를 요구한다. */
export interface SeaRouteRequest {
  fromLat: number
  fromLon: number
  toLat: number
  toLon: number
  /** 우회 경유지 (`PRD §11.3`). 없으면 직항이다. */
  via?: { lat: number; lon: number } | null
}

/** `API_SPEC §3.11` 응답. `coordinates`는 GeoJSON 순서(경도, 위도)다. */
export interface SeaRouteLine {
  coordinates: [number, number][]
  lengthNm: number
  legs: number
}

/** 같은 질문은 같은 열쇠다 — 훅의 상태와 요청 중복 제거가 이 문자열로 갈린다. */
export function seaRouteKey(request: SeaRouteRequest): string {
  const via = request.via ? `${request.via.lat},${request.via.lon}` : ''
  return `${request.fromLat},${request.fromLon}|${via}|${request.toLat},${request.toLon}`
}

function query(request: SeaRouteRequest): string {
  const params = new URLSearchParams({
    from_lat: String(request.fromLat),
    from_lon: String(request.fromLon),
    to_lat: String(request.toLat),
    to_lon: String(request.toLon),
  })
  if (request.via) {
    params.set('via_lat', String(request.via.lat))
    params.set('via_lon', String(request.via.lon))
  }
  return params.toString()
}

/** 응답이 계약 모양인가 — 모양이 다르면 「못 받았다」로 다룬다(선을 지어내지 않는다). */
function toLine(body: unknown): SeaRouteLine | null {
  const data = (body as { data?: Record<string, unknown> } | null)?.data
  if (typeof data !== 'object' || data === null) return null
  const coordinates = data.coordinates
  if (!Array.isArray(coordinates) || typeof data.length_nm !== 'number') return null
  if (typeof data.legs !== 'number') return null
  const pairs: [number, number][] = []
  for (const pair of coordinates) {
    if (!Array.isArray(pair) || pair.length !== 2) return null
    const [lon, lat] = pair as unknown[]
    if (typeof lon !== 'number' || typeof lat !== 'number') return null
    pairs.push([lon, lat])
  }
  return { coordinates: pairs, lengthNm: data.length_nm, legs: data.legs }
}

/** `GET /ports/sea-route` (`API_SPEC §3.11`). 실패·계약 위반은 던진다. */
export async function fetchSeaRoute(
  request: SeaRouteRequest,
  fetchImpl: typeof fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<SeaRouteLine> {
  const response = await fetchImpl(`${baseUrl}/ports/sea-route?${query(request)}`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  const body = (await response.json().catch(() => null)) as unknown
  if (!response.ok) throw new Error(`해상 경로 조회 실패 (HTTP ${response.status})`)
  const line = toLine(body)
  if (line === null) throw new Error('해상 경로 응답이 계약과 다릅니다.')
  return line
}

/** 한 요청의 상태 — 아직 없음(`undefined`) · 받음 · 못 받음. */
export type SeaRouteState = SeaRouteLine | 'failed'

/**
 * 요청 목록의 선을 받아 둔다. 열쇠(`seaRouteKey`)가 같은 요청은 한 번만 묻는다.
 *
 * 의존성은 **열쇠를 이어 붙인 문자열**이다 — 요청 배열은 호출부가 렌더마다 새로 만들므로
 * 배열 자체를 의존성으로 두면 매 렌더 다시 묻는다.
 *
 * **진행 중인 요청도 재사용한다.** 응답이 오기 전에 목록이 바뀌어 effect가 다시 돌면
 * 같은 열쇠를 또 묻게 되는데, 열쇠별 Promise를 ref에 두면 그 사이의 렌더는 앞 요청에
 * 올라탄다. 실패 이유는 `console.warn`으로 남긴다 — 화면은 「못 받았다」만 알고 이유는
 * 콘솔이 갖는다(`#1616` 가드는 `console.error`만 실패로 본다).
 */
export function useSeaRoutes(
  requests: readonly SeaRouteRequest[],
  fetchImpl: typeof fetch = globalThis.fetch,
): Record<string, SeaRouteState> {
  const [lines, setLines] = useState<Record<string, SeaRouteState>>({})
  const inFlight = useRef(new Map<string, Promise<SeaRouteLine>>())
  const wanted = requests.map(seaRouteKey).join('\n')

  useEffect(() => {
    let alive = true
    // 같은 열쇠는 한 번만 — 대시보드의 두 배가 같은 항로를 갈 수 있다.
    const pending = new Map<string, SeaRouteRequest>()
    for (const request of requests) {
      const key = seaRouteKey(request)
      if (!(key in lines) && !pending.has(key)) pending.set(key, request)
    }
    for (const [key, request] of pending) {
      let promise = inFlight.current.get(key)
      if (promise === undefined) {
        promise = fetchSeaRoute(request, fetchImpl)
        inFlight.current.set(key, promise)
        promise.finally(() => inFlight.current.delete(key)).catch(() => undefined)
      }
      promise.then(
        (line) => {
          if (alive) setLines((prev) => ({ ...prev, [key]: line }))
        },
        (reason: unknown) => {
          console.warn('[seaRoute]', key, reason)
          if (alive) setLines((prev) => ({ ...prev, [key]: 'failed' }))
        },
      )
    }
    return () => {
      alive = false
    }
    // `wanted`가 요청 목록을 대표한다 — 위 주석 참조.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted, fetchImpl])

  return lines
}
