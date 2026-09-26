import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { hasBasemap } from '../fleet/basemap'
import { seaRouteKey, useSeaRoutes, type RouteLine } from '../fleet/seaRoute'
import { getKnownRouteSource } from '../map/routeGeometry'
import { routeDisclosure } from '../map/routeDisclosure'
import { adaptComparisonRoutes, adaptRouteMap } from '../map/adapters'
import { MapRendererHost, type MapRendererEvent } from '../map/renderer'
import type { MapLibreMapModel } from '../map/mapLibreRenderer'
import { routeFeatureCollection } from '../map/routeModel'
import './VoyageRouteMap.css'
import type { SamplePort } from '../ports/samplePorts'
import { HarborTransitionShell } from '../map/HarborTransitionShell'
import { MapAlternative } from '../map/MapAlternative'
import { classifyMapFailure, type MapFailure } from '../map/mapFailure'

/**
 * 항로 비교의 지도 (`#1265` · `#1300`).
 *
 * ## 선은 공개 해상 경로망 위의 바닷길이다
 *
 * 종전에는 현재 위치와 목적항을 잇는 **대권선** 하나였다 — 최단 경로라 육지를 가로질렀고,
 * 캡션이 「최단 경로일 뿐」이라고 받았다. `#1300`(E-6 결정)으로 서버가 Eurostat 경로망에서
 * 찾은 선을 그린다(`FleetMap` · `API_SPEC §3.11`). **그래도 실제 항해 계획은 아니다** —
 * 경로망은 이 배의 운항 계획·수심·기상을 모른다. 캡션이 그 사실을 받는다.
 *
 * ## 선은 하나 또는 둘이다
 *
 * 우회 경유지(고급 설정 · `PRD §11.3`)를 넣었을 때만 **우회 선**이 하나 더 그려진다 —
 * 「현재 위치 → 경유지 → 목적항」. 감속은 직항과 같은 길이라 선이 늘지 않는다. 경유지가
 * 없으면 종전처럼 직항 선 하나이고, 우회·감속의 차이는 아래 표가 말한다.
 *
 * ## 표의 거리는 선의 길이가 아니다
 *
 * 계산 거리는 사용자 입력 또는 **대권거리**다(`PRD §15.2` · `TECH_SPEC §6.3`). 선은 표시일
 * 뿐이라 캡션은 「표의 직항 거리가 이 선의 길이」라고 말하지 않는다.
 *
 * ## 그리지 못하면 아무것도 내지 않는다
 *
 * 좌표는 **선택 입력**이라 비어 있는 것이 기본 경로다(`types.ts` 「직항 거리가 있으면
 * 서버가 그것을 먼저 쓴다」). 없을 때 빈 지도나 오류를 내면 **정상 상태가 고장으로
 * 읽힌다.** 자산이 없을 때도 같다 — 개략도(`PositionChart`)는 선박 기반이라 이 자리에
 * 쓸 수 없다.
 */

/**
 * 빈 배열을 **모듈 상수로** 둔다. 렌더마다 새 배열을 넘기면 `FleetMap`의 마커 effect
 * 의존 배열이 매번 달라져 무한 재실행이 된다(`FleetMap`의 `NO_ROUTES`와 같은 이유).
 */
/**
 * 선을 못 받았을 때의 문장 — 선대 문안(「위치만 표시합니다」)은 이 화면에서 거짓이다(선박을
 * 그리지 않는다). 표시 문구(`AGENTS §4.6`)라 디자인 담당이 바꿀 수 있다.
 */
const ROUTE_UNAVAILABLE_ON_COMPARISON =
  '항로선을 불러오지 못했습니다 — 지도에 경로가 그려지지 않습니다. 거리·속력의 차이는 아래 표에 있습니다.'

/**
 * 직항·우회 중 **하나만** 못 받았을 때의 문장 (`#1856`) — 받은 선은 그려져 있으므로 위 문장은
 * 거짓이다. 표시 문구(`AGENTS §4.6`) · 개발 임시안이며 디자인 담당이 바꿀 수 있다.
 *
 * 재시도 신호는 넘기지 않는다 — 「비교하기」를 다시 누르면 부모(`ScenarioComparison`)가
 * 계산 중 분기에서 결과 트리를 내렸다 다시 올리므로 이 지도가 **새로 마운트되어** 못 받은
 * 선을 처음부터 다시 묻는다.
 */
const ROUTE_PARTIAL_ON_COMPARISON =
  '항로선 일부를 불러오지 못했습니다 — 그려지지 않은 경로가 있습니다. 거리·속력의 차이는 아래 표에 있습니다.'

const loadComparisonRenderer = () => import('../map/mapLibreRenderer').then(({ mapLibreRenderer }) => mapLibreRenderer)

interface VoyageRouteMapProps {
  currentLat: string
  currentLon: string
  destinationLat: string
  destinationLon: string
  /** 목적항 이름. 비어 있으면 선 이름을 「목적항」으로 둔다. */
  destinationName?: string
  /** 우회 경유지 (`#1300`). 둘 다 있을 때만 우회 선을 그린다. */
  detourWaypointLat?: string
  detourWaypointLon?: string
  detourWaypointName?: string
  /** 부모 화면이 이미 조회한 항만 목록. 지도 때문에 같은 API를 다시 호출하지 않는다. */
  samplePorts?: readonly SamplePort[]
  /**
   * 대체 정보(접힌 텍스트)의 제목 (`#1949`).
   *
   * 기본 문안 「항로 비교 지도」는 **이 화면 기준**이라, 부품을 빌려 쓰는 화면에서는
   * 그대로 두면 **틀린 말이 된다** — 실시간 CII가 이것을 쓰면서 「항로 비교 지도 텍스트
   * 정보」가 그 화면에 나왔다. `FleetMap`의 `ariaLabel`·`caption`이 같은 이유로 이미
   * 호출부에 열려 있다.
   */
  alternativeTitle?: string
}

export function VoyageRouteMap({
  currentLat,
  currentLon,
  destinationLat,
  destinationLon,
  destinationName = '',
  detourWaypointLat = '',
  detourWaypointLon = '',
  detourWaypointName = '',
  samplePorts = [],
  alternativeTitle = '항로 비교 지도',
}: VoyageRouteMapProps) {
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [rendererFailure, setRendererFailure] = useState<MapFailure | null>(null)
  const [rendererAttempt, setRendererAttempt] = useState(0)
  const hintId = useId()
  useEffect(() => {
    let alive = true
    void hasBasemap().then((found) => {
      if (alive) setBasemap(found)
    })
    return () => {
      alive = false
    }
  }, [])

  const routes = useMemo<RouteLine[]>(() => {
    return [...adaptComparisonRoutes({
      currentLat, currentLon, destinationLat, destinationLon, destinationName,
      detourWaypointLat, detourWaypointLon, detourWaypointName,
    })]
  }, [currentLat, currentLon, destinationLat, destinationLon, destinationName, detourWaypointLat, detourWaypointLon, detourWaypointName])

  const adapted = useMemo(() => adaptRouteMap(routes, samplePorts), [routes, samplePorts])
  const asks = adapted.routes
  const lines = useSeaRoutes(asks.map(({ request }) => request))
  const failed = asks.filter(({ request }) => lines[seaRouteKey(request)] === 'failed').length
  const routeFailure = failed === 0
    ? null
    : failed === asks.length ? ROUTE_UNAVAILABLE_ON_COMPARISON : ROUTE_PARTIAL_ON_COMPARISON

  const rendererModel = useMemo<MapLibreMapModel>(() => {
    const bounds = asks.flatMap(({ request }) => {
      const coordinates: [number, number][] = [
        [request.fromLon, request.fromLat], [request.toLon, request.toLat],
      ]
      if (request.via) coordinates.push([request.via.lon, request.via.lat])
      return coordinates
    })
    return {
      mode: 'comparison', markers: [], ports: adapted.ports,
      routes: { data: routeFeatureCollection(asks, lines), attribution: getKnownRouteSource('searoute/marnet')!.attribution, bounds },
    }
  }, [adapted.ports, asks, lines])
  const handleRendererEvent = useCallback((event: MapRendererEvent) => {
    if (event.type === 'ready') setRendererFailure(null)
    if (event.type === 'error') setRendererFailure(classifyMapFailure(event.error))
  }, [])

  if (routes.length === 0 || basemap !== true) return null
  const detour = routes.length === 2
  const source = getKnownRouteSource('searoute/marnet')!
  const disclosure = routeDisclosure({
    mode: 'comparison',
    source,
    kinds: detour ? ['DIRECT', 'DETOUR'] : ['DIRECT'],
  })

  return (
    <div className="voyage-route-map">
      <HarborTransitionShell onGlobeEvent={handleRendererEvent} renderGlobe={(onEvent) => (
        <MapRendererHost
          key={rendererAttempt}
          className="voyage-route-map__canvas"
          model={rendererModel}
          loadRenderer={loadComparisonRenderer}
          ariaLabel={
            detour
              ? '현재 위치에서 목적항까지의 항로 지도. 공개 해상 경로망 위의 직항 경로와 우회 경유지를 지나는 우회 경로 — 실제 항해 계획이 아닙니다.'
              : '현재 위치에서 목적항까지의 항로 지도. 공개 해상 경로망 위의 경로 — 실제 항해 계획이 아닙니다.'
          }
          ariaDescribedBy={hintId}
          onEvent={onEvent}
        />
      )} />
      {routeFailure === null ? null : <p className="voyage-route-map__status">{routeFailure}</p>}
      <p className="voyage-route-map__hint" id={hintId}>{disclosure.visibleText}</p>
      <MapAlternative id={`${hintId}-alternative`} title={alternativeTitle}
        failure={rendererFailure}
        onRetry={() => { setRendererFailure(null); setRendererAttempt((value) => value + 1) }}
        items={routes.map((route) => `${route.kind === 'DETOUR' ? '우회' : '직항'}: 출발 ${route.departureLat}, ${route.departureLon} · 도착 ${route.arrivalLat}, ${route.arrivalLon}`)} />
    </div>
  )
}
