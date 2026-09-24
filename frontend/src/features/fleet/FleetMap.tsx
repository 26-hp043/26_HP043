import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import './FleetMap.css'
import type { FleetVessel } from './types'
import { BASEMAP_FONTS_URL, BASEMAP_URL, INITIAL_ZOOM, MAX_ZOOM } from './basemap'
import { seaRouteKey, useSeaRoutes, type SeaRouteRequest, type SeaRouteState } from './seaRoute'
import { VESSEL_GRID, VESSEL_PATHS } from '../../components/vesselShape'
import {
  isAtRisk,
  missingPositionAria,
  missingPositionText,
  NO_POSITION_RECORDED_TEXT,
} from './fleetRules'

/**
 * 선대 지도 (`#763`).
 *
 * ## 타일은 우리 오리진의 파일 하나다
 *
 * 키가 없고 런타임 외부 요청이 없다 — 자세한 근거는 `basemap.ts`. 자산이 없으면 이
 * 컴포넌트는 **그려지지 않고**, 호출부가 개략도(`PositionChart`)를 대신 그린다.
 *
 * ## 마커는 개략도와 같은 언어를 쓴다
 *
 * 배 모양(`vesselShape`)과 등급 색을 그대로 옮긴다. 지도로 바뀌었다고 기호가 달라지면
 * 같은 화면의 등급 분포·선박 카드와 읽는 법이 갈린다.
 *
 * ⚠️ **등급을 색으로만 말하지 않는다**(`DESIGN_SYSTEM §14`). 마커에 등급 문자를 함께
 * 적는다 — 개략도는 SVG `<pattern>`으로 무늬를 덮지만, 지도 마커는 DOM 요소라 같은
 * 패턴 정의를 쓸 수 없다. **문자가 그 자리를 대신한다**(`§15.1`이 「패턴 없는 A」를
 * 허용하는 근거와 같다 — 등급 문자가 항상 함께 놓인다).
 *
 * ## 항로선은 진행 중 항차에만
 *
 * `route`가 있는 선박만 그린다. 없는 배는 점만 남는다 — **없는 항로를 지어내지 않는다.**
 *
 * ## 선은 공개 해상 경로망 위의 바닷길이다 (`#1300` · `PRD §5.2`)
 *
 * 종전에는 두 항을 잇는 **대권선**이었다 — 최단 경로라 육지를 가로질렀다(`#1275`). 지금은
 * 서버(`API_SPEC §3.11`)가 Eurostat 경로망에서 찾은 선을 받아 그린다(`seaRoute.ts`).
 * **표의 거리는 그대로다** — 계산 거리는 사용자 입력 또는 대권거리이고(`PRD §15.2`) 이
 * 선은 표시일 뿐이다. 서버가 선을 주지 못하면 **그리지 않고 그 사실을 적는다** —
 * 대권선으로 되돌리면 캡션(「경로망 위의 경로」)이 거짓이 된다.
 */

/**
 * 선박과 무관하게 그리는 항로 하나 (`#1265` · `#1300`).
 *
 * 항로 비교(`UIFLOW 2-2`)가 쓴다. 직항은 현재 위치 → 목적항이고, 고급 설정에 우회
 * 경유지를 넣으면 **우회 선이 하나 더** 온다(`kind: 'DETOUR'` · `via`) — 세 시나리오 중
 * 감속은 직항과 같은 길이라 선이 둘을 넘지 않는다(`PRD §11.3`).
 */
export interface RouteLine {
  name: string
  departureLat: number
  departureLon: number
  arrivalLat: number
  arrivalLon: number
  /** 우회 경유지. 있으면 「출발 → 경유지 → 도착」으로 잇는다. */
  via?: { lat: number; lon: number } | null
  /** 선의 종류. 생략하면 직항이다 — 파선(`DESIGN_SYSTEM §9.5`). 우회는 점선이다. */
  kind?: 'DIRECT' | 'DETOUR'
}

/** 서버에 물을 항로 하나 — 선박의 진행 중 항차와 `routes` 프롭이 같은 모양으로 모인다. */
interface RouteAsk {
  name: string
  kind: 'DIRECT' | 'DETOUR'
  request: SeaRouteRequest
}

/** 못 그린 선이 있을 때 지도 옆에 적는 문장 — 선을 지어내지 않고 그 사실을 말한다. */
export const ROUTE_UNAVAILABLE_TEXT = '항로선을 불러오지 못했습니다 — 위치만 표시합니다.'

/**
 * 선 **일부만** 못 받았을 때의 문장 (`#1856`). 받은 선은 그려져 있으므로 「위치만 표시합니다」는
 * 거짓이 된다 — 전부 못 받았을 때와 문장을 가른다. 표시 문구(`AGENTS §4.6`) · 개발 임시안이며
 * 디자인 담당이 바꿀 수 있다.
 */
export const ROUTE_PARTIAL_TEXT = '항로선 일부를 불러오지 못했습니다 — 그리지 못한 항로는 위치만 표시합니다.'

/**
 * 경로망 출처 표기 (`#1300` 결정 5항 — `README` · `NOTICE` · 화면 세 곳).
 *
 * 지도 오른쪽 아래 접힌 출처 컨트롤에 「© OpenStreetMap」과 나란히 실린다(MapLibre가
 * 소스별 attribution을 모은다). 경로망 데이터는 Eurostat SeaRoute(EUPL-1.2), 그것을
 * 번들한 파이썬 패키지 `searoute`는 Apache-2.0이다. ⚠️ 문구·자리는 **개발 임시안**이며
 * 디자인 담당 검토 대상이다(`DESIGN_SYSTEM §9.5` 출처 표기는 「© OpenStreetMap」으로 확정돼 있다).
 */
export const ROUTE_ATTRIBUTION =
  '해상 경로망 © Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)'

/**
 * 빈 기본값을 **모듈 상수로** 둔다.
 *
 * `routes = []`로 쓰면 렌더마다 새 배열이 만들어져 아래 마커 effect의 의존 배열이
 * 매번 달라진다 — **무한 재실행**이 된다. 호출부가 프롭을 생략해도 같은 참조다.
 */
const NO_ROUTES: readonly RouteLine[] = []

interface FleetMapProps {
  vessels: FleetVessel[]
  /** 선박에서 파생하지 않는 항로. 생략하면 종전과 같다. */
  routes?: readonly RouteLine[]
  /**
   * 낭독 라벨·읽는 법 문구 (`#1265`).
   *
   * 기본 문안은 **선대 화면 기준**이라(「선박 N척」·「테두리가 굵은 표는 주의 대상」)
   * 선박을 그리지 않는 화면에서는 그대로 두면 **틀린 말이 된다.** 생략하면 종전과 같다.
   */
  ariaLabel?: string
  caption?: ReactNode
  /**
   * 서버가 항로선을 주지 못했을 때 지도 옆에 적는 문장 (`#1300`). 기본 문안은 선대 화면
   * 기준(「위치만 표시합니다」)이라 선박을 그리지 않는 화면에서는 틀린 말이 된다 —
   * `ariaLabel`·`caption`과 같은 이유로 호출부가 넘긴다. 생략하면 선대 문안이다.
   */
  routeUnavailableText?: string
  /** 선 **일부만** 못 받았을 때의 문장 (`#1856`). `routeUnavailableText`와 같은 이유로 호출부가 넘긴다. */
  routePartialText?: string
  /**
   * 재시도 신호 (`#1856`). 값이 바뀌면 **못 받은 선만** 다시 묻는다 — 받은 선은 다시 묻지
   * 않는다(`useSeaRoutes`). 생략하면 실패한 선은 이 지도가 떠 있는 동안 다시 묻지 않는다.
   */
  retryToken?: number
}

/** 좌표가 있는 선박만. 숫자로 되돌리는 곳은 여기뿐이다(지도가 숫자를 요구한다). */
interface Placed {
  vessel: FleetVessel
  lat: number
  lon: number
}

function placed(vessels: FleetVessel[]): Placed[] {
  return vessels.flatMap((vessel) => {
    if (vessel.lat === null || vessel.lon === null) return []
    const lat = Number(vessel.lat)
    const lon = Number(vessel.lon)
    return Number.isFinite(lat) && Number.isFinite(lon) ? [{ vessel, lat, lon }] : []
  })
}

/** 마커 DOM. 배 모양 + 등급색 + 등급 문자. */
function markerElement(vessel: FleetVessel): HTMLElement {
  const root = document.createElement('div')
  root.className = 'fleetmap__marker'
  const rating = vessel.ytdRating
  root.classList.add(rating ? `fleetmap__marker--${rating.toLowerCase()}` : 'fleetmap__marker--none')
  if (isAtRisk(vessel)) root.classList.add('fleetmap__marker--risk')

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', `0 0 ${VESSEL_GRID} ${VESSEL_GRID}`)
  svg.setAttribute('aria-hidden', 'true')
  /*
   * 선수 방향 (#1824 · `DESIGN_SYSTEM §9.5` v2.28) — 서버가 준 `course_deg`만큼
   * 돌린다(북 = 0 · 시계 방향).
   *
   * ⚠️ **화면이 계산하지 않는다.** 같은 방위를 내는 `initial_bearing_deg`가 서버에
   * 있고 항로 비교의 기상 보정이 그 함수를 쓴다(`#1804` · `#1672` 회신 ⑴) — 여기서
   * 다시 계산하면 지도와 항로 비교가 다른 값을 말할 수 있다.
   *
   * **값이 없으면 돌리지 않는다** — 없는 방향을 0°(북)로 그리면 「북쪽으로 간다」는
   * 거짓을 그리는 것이다. 정박·묘박처럼 목적항이 없는 배가 여기 든다.
   *
   * 배지는 함께 돌지 않는다 — 글자가 뒤집히면 등급을 읽을 수 없다(`§14` 문자 채널).
   */
  const course = vessel.courseDeg === null ? null : Number(vessel.courseDeg)
  if (course !== null && Number.isFinite(course)) {
    svg.style.transform = `rotate(${course}deg)`
  }
  for (const d of VESSEL_PATHS) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', d)
    svg.appendChild(path)
  }
  root.appendChild(svg)

  /*
   * 정박 · 묘박의 닻 배지 (#1824 · 정본 v2.28). `detail_status`의 NOT_UNDER_WAY
   * 다섯이 여기 든다 — 접안 · 묘박 · 표류 · 선박 간 이적 · 운하 통과.
   * **배 모양은 그대로**다. 갈리는 것은 이 배지 하나이고, 낭독은 아래 이름표가 받는다.
   */
  const moored = vessel.underwayState === 'NOT_UNDER_WAY'
  if (moored) {
    const anchor = document.createElement('span')
    anchor.className = 'fleetmap__anchor'
    anchor.setAttribute('aria-hidden', 'true')
    anchor.textContent = '⚓'
    root.appendChild(anchor)
  }

  const label = document.createElement('span')
  label.className = 'fleetmap__badge'
  // 색 단독 금지 (`§14`). 등급이 없으면 「—」로 둔다 — 빈 칸은 「A」로 읽힌다.
  label.textContent = rating ?? '—'
  root.appendChild(label)

  root.setAttribute('role', 'img')
  root.setAttribute(
    'aria-label',
    `${vessel.name} · 등급 ${rating ?? '없음'}${moored ? ' · 정박 중' : ''}${isAtRisk(vessel) ? ' · 주의' : ''}`,
  )
  return root
}

/** 그릴 항로 목록. 진행 중 항차가 있는 선박 한 줄씩 + `routes` 프롭. */
function routeAsks(points: Placed[], extra: readonly RouteLine[]): RouteAsk[] {
  const fromVessels = points.flatMap(({ vessel }): RouteAsk[] => {
    const route = vessel.route
    if (route == null) return []
    const request: SeaRouteRequest = {
      fromLat: Number(route.departureLat),
      fromLon: Number(route.departureLon),
      toLat: Number(route.arrivalLat),
      toLon: Number(route.arrivalLon),
    }
    if (!Object.values(request).every((v) => Number.isFinite(v))) return []
    return [{ name: vessel.name, kind: 'DIRECT', request }]
  })
  const fromProps = extra.map(
    (route): RouteAsk => ({
      name: route.name,
      kind: route.kind ?? 'DIRECT',
      request: {
        fromLat: route.departureLat,
        fromLon: route.departureLon,
        toLat: route.arrivalLat,
        toLon: route.arrivalLon,
        via: route.via ?? null,
      },
    }),
  )
  return fromVessels.concat(fromProps)
}

/** 받아 둔 선만 GeoJSON으로. 아직 없거나 못 받은 것은 **빈자리**다 — 지어내지 않는다. */
function routeCollection(
  asks: readonly RouteAsk[],
  lines: Record<string, SeaRouteState>,
): maplibregl.GeoJSONSourceSpecification['data'] {
  return {
    type: 'FeatureCollection',
    features: asks.flatMap((ask) => {
      const line = lines[seaRouteKey(ask.request)]
      if (line === undefined || line === 'failed' || line.coordinates.length < 2) return []
      return [
        {
          type: 'Feature' as const,
          properties: { name: ask.name, kind: ask.kind },
          geometry: { type: 'LineString' as const, coordinates: line.coordinates },
        },
      ]
    }),
  }
}

/** 지도 페인트가 CSS 변수를 읽지 못하므로 계산된 값을 꺼낸다. 비면 빈 문자열이다. */
function accentColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--semantic-info').trim()
}

export function FleetMap({
  vessels,
  routes = NO_ROUTES,
  ariaLabel,
  caption,
  routeUnavailableText = ROUTE_UNAVAILABLE_TEXT,
  routePartialText = ROUTE_PARTIAL_TEXT,
  retryToken,
}: FleetMapProps) {
  /*
   * 좌표가 없는 선박은 `placed()`에서 **조용히 빠진다** (#1103).
   *
   * 개략도(`PositionChart`)는 몇 척이 빠졌는지 적는데 이 지도만 아무 말도 하지
   * 않았다 — 4척 중 1척이 미입력이면 지도에 3척만 그려지고 **그 3척이 선대 전부로**
   * 읽힌다. 문구는 개략도와 **같은 원천**(`fleetRules`)을 쓴다.
   */
  const shown = placed(vessels).length
  const missingText = missingPositionText(vessels.length, shown)
  // 렌더마다 새 배열이면 아래 effect가 매번 다시 돈다 — `NO_ROUTES`와 같은 이유로 고정한다.
  const asks = useMemo(() => routeAsks(placed(vessels), routes), [vessels, routes])
  const lines = useSeaRoutes(
    asks.map((ask) => ask.request),
    undefined,
    retryToken,
  )
  /*
   * 못 받은 선이 **전부인가 일부인가** (`#1856`). 서버는 세 점 요청을 한 덩어리로 실패시키므로
   * 우회만 실패하고 직항은 그려질 수 있다 — 그때 「그려지지 않습니다」라고 적으면 거짓이다.
   */
  const failedAsks = asks.filter((ask) => lines[seaRouteKey(ask.request)] === 'failed').length
  const routeFailure =
    failedAsks === 0 ? null : failedAsks === asks.length ? routeUnavailableText : routePartialText

  /*
   * 캔버스 자리를 **ref가 아니라 state로 잡는다** (`#1645`).
   *
   * 종전에는 `useRef` + 의존성 없는 effect였다. 그런데 좌표가 한 척도 없으면 아래
   * 분기가 **캔버스 자체를 그리지 않으므로** 첫 실행에서 `container.current`가
   * `null`이라 지도를 만들지 않고 끝났고, 나중에 위치가 들어와 캔버스가 그려져도
   * **effect가 다시 돌지 않아** 그 자리는 빈 채로 남았다 — 새로고침해야 보였다.
   *
   * ref 콜백이 노드를 state로 올리면 붙고 떨어지는 것이 렌더에 잡힌다. 좌표가
   * 사라져 캔버스가 빠질 때도 같은 effect의 정리가 돌아 지도가 남지 않는다.
   */
  const [canvas, setCanvas] = useState<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (canvas === null || map.current !== null) return

    /*
     * PMTiles 프로토콜은 **전역에 한 번만** 등록한다. 같은 이름으로 두 번 등록하면
     * MapLibre가 던진다 — 화면을 오갈 때마다 이 효과가 다시 도는데, 그때 앱이 죽는다.
     */
    const registry = globalThis as { __bluelogPmtiles?: Protocol }
    if (registry.__bluelogPmtiles === undefined) {
      const protocol = new Protocol()
      maplibregl.addProtocol('pmtiles', protocol.tile)
      registry.__bluelogPmtiles = protocol
    }

    const instance = new maplibregl.Map({
      container: canvas,
      style: {
        version: 8,
        // 글리프도 **우리 오리진**이다. CDN을 가리키면 지도 배경은 오프라인에서
        // 뜨는데 글자만 사라진다 — 그 상태가 가장 나쁘다(고장인지 판단할 수 없다).
        glyphs: `${BASEMAP_FONTS_URL}/{fontstack}/{range}.pbf`,
        sources: {
          protomaps: {
            type: 'vector',
            url: `pmtiles://${BASEMAP_URL}`,
            attribution: '© OpenStreetMap',
          },
          /*
           * 항로선 소스는 **처음부터** 둔다 — 출처 표기(`ROUTE_ATTRIBUTION`)가 지도 컨트롤에
           * 실리려면 스타일에 소스가 있어야 한다. 데이터는 아래 effect가 채운다.
           */
          routes: {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
            attribution: ROUTE_ATTRIBUTION,
          },
        },
        layers: layers('protomaps', namedFlavor('light'), { lang: 'ko' }),
      },
      center: [127, 30],
      zoom: INITIAL_ZOOM,
      maxZoom: MAX_ZOOM,
      // 지도는 **보는 것**이지 돌리는 것이 아니다. 회전·기울임을 막으면 북쪽이 늘 위다.
      dragRotate: false,
      pitchWithRotate: false,
      touchZoomRotate: true,
      attributionControl: { compact: true },
    })
    instance.touchZoomRotate.disableRotation()
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    // 지도 오류를 **반드시 드러낸다** (`#1146`).
    //
    // maplibre는 오류를 `error` 이벤트로만 알린다. 듣는 곳이 없으면 타일이 한 장도
    // 뜨지 않아도 화면에는 스타일 배경색만 칠해진 회색 사각형이 남고, 콘솔에도
    // 아무것도 찍히지 않는다 — 고장인지 로딩 중인지 구분할 수 없는 상태다.
    // 2026-09-15에 워커 404로 그 상태를 겪었고, 원인을 좁히는 데 오래 걸렸다.
    instance.on('error', (event) => {
      console.error('[FleetMap] 지도 오류:', event.error?.message ?? String(event))
    })
    instance.on('load', () => setReady(true))
    map.current = instance

    return () => {
      instance.remove()
      map.current = null
      // 마커는 지도와 함께 사라진다 — 참조만 남으면 다음 지도에서 지우려다 헛돈다.
      markers.current = []
      setReady(false)
    }
  }, [canvas])

  /*
   * 마커와 항로선은 **다른 effect**다 (`#1300` 리뷰). 한 effect에 두면 항로 응답이 올 때마다
   * 마커를 지우고 다시 만들어 — 마커 DOM 노드가 바뀐다. 마커에 붙는 것(팝오버 · 초점 ·
   * `#1831`)이 그때마다 떨어진다. 마커는 `vessels`가 바뀔 때만, 항로선은 응답이 올 때만.
   */
  useEffect(() => {
    const instance = map.current
    if (instance === null || !ready) return

    const points = placed(vessels)

    for (const marker of markers.current) marker.remove()
    markers.current = points.map(({ vessel, lat, lon }) =>
      new maplibregl.Marker({ element: markerElement(vessel), anchor: 'center' })
        .setLngLat([lon, lat])
        .addTo(instance),
    )
  }, [vessels, ready])

  useEffect(() => {
    const instance = map.current
    if (instance === null || !ready) return

    const collection = routeCollection(asks, lines)
    const source = instance.getSource('routes') as maplibregl.GeoJSONSource | undefined
    if (source === undefined) {
      /*
       * 소스는 스타일이 갖고 있다(출처 표기 때문 — 위 `sources.routes`). 여기 오는 것은
       * 대역(테스트)처럼 스타일이 없는 지도뿐이라 그때만 만든다.
       */
      instance.addSource('routes', { type: 'geojson', data: collection, attribution: ROUTE_ATTRIBUTION })
    } else {
      source.setData(collection)
    }
    if (instance.getLayer?.('routes') === undefined) {
      /*
       * **색을 먼저 읽고, 유효한 값일 때만 넣는다** (`#1265`).
       *
       * 종전에는 `line-color`에 `'var-replaced-at-runtime'`를 넣고 그 뒤에
       * `setPaintProperty`로 덮었다. 그런데 그 문자열은 **유효한 색이 아니다** —
       * MapLibre는 스타일 검증에 실패하면 에러를 내고 **레이어를 추가하지 않은 채
       * 반환**한다. 레이어가 없으니 뒤따르는 `setPaintProperty`도 대상이 없고,
       * 결국 **항로선이 한 번도 그려지지 않는다.** 지도는 멀쩡히 뜨므로 눈으로는
       * 「선이 없는 항차」로만 보인다.
       *
       * CSS 변수는 지도 페인트가 읽지 못하므로 계산된 값을 꺼내 쓰는 것은 그대로다.
       *
       * ⚠️ **리터럴 대체색을 두지 않는다**(`#1052`의 판단). 종전에 `#1f6feb`를
       * 남겨 두었더니 `--semantic-info`가 존재하지 않는 동안 **그 리터럴이 언제나
       * 실제 색**이었고, `§9.5` 🔒가 정한 토큰이 지켜지지 않는 것을 아무도 몰랐다.
       * 값이 비면 `line-color`를 **아예 넣지 않아** MapLibre 기본색(검정)으로
       * 그려지게 둔다 — 규격과 어긋난 상태가 화면에서 바로 보인다.
       *
       * **선은 두 종류다** (`#1300`). 직항은 종전 그대로 파선 `2 1.5`(`§9.5` 🔒)이고,
       * 우회는 **같은 색의 점선** `0.5 2`다 — 색이 아니라 **선의 결**로 가르므로 색을
       * 못 봐도 구분된다(`§14`). 카드의 도식(`ScenarioRouteGlyph`)이 우회를 점선으로
       * 그리는 것과 같은 언어다. ⚠️ 우회 선의 결은 **개발 임시안**이다 — 디자인 담당
       * 확인 전까지 새 토큰·새 색을 만들지 않고 직항의 색을 그대로 쓴다.
       */
      const accent = accentColor()
      const paint = {
        ...(accent === '' ? {} : { 'line-color': accent }),
        'line-width': 2,
        'line-opacity': 0.9,
      }
      instance.addLayer({
        id: 'routes',
        type: 'line',
        source: 'routes',
        filter: ['!=', ['get', 'kind'], 'DETOUR'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        // 파선이라 색을 못 봐도 배경의 도로·경계선과 구분된다 (`§14`).
        paint: { ...paint, 'line-dasharray': [2, 1.5] },
      })
      instance.addLayer({
        id: 'routes-detour',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'kind'], 'DETOUR'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { ...paint, 'line-dasharray': [0.5, 2] },
      })
    }

    // 처음 한 번만 그려진 것에 맞춘다 — 갱신마다 맞추면 사용자가 확대해 둔 자리가 튄다.
    // 선박 좌표는 `asks`가 아니라 마커에서 — 항차 없는 배도 화면 안에 들어야 한다.
    const placedPoints = placed(vessels)
    if ((placedPoints.length > 0 || asks.length > 0) && instance.getZoom() === INITIAL_ZOOM) {
      const bounds = new maplibregl.LngLatBounds()
      for (const { lat, lon } of placedPoints) bounds.extend([lon, lat])
      /*
       * 명시 경로의 **양 끝도** 넣는다 (`#1265`).
       *
       * 종전 조건은 `points.length > 0`이라 **선박이 없는 화면에서는 아예 돌지 않았다.**
       * 항로 비교는 선박을 그리지 않으므로 지도가 기본 뷰(`INITIAL_ZOOM`)에 머물고,
       * 그린 선이 **화면 밖에 있을 수 있다** — 지도는 떴는데 항로만 안 보이는 상태가 된다.
       */
      for (const { request } of asks) {
        bounds.extend([request.fromLon, request.fromLat])
        bounds.extend([request.toLon, request.toLat])
        if (request.via) bounds.extend([request.via.lon, request.via.lat])
      }
      instance.fitBounds(bounds, { padding: 48, maxZoom: 6, animate: false })
    }
  }, [vessels, asks, ready, lines])

  if (vessels.length > 0 && shown === 0) {
    // 전부 빠진 경우는 빈 지도를 띄우지 않는다 — 빈 바다는 「선박이 없다」로 읽힌다.
    return (
      <div className="fleetmap">
        <p className="fleetmap__missing">{NO_POSITION_RECORDED_TEXT}</p>
      </div>
    )
  }

  return (
    <div className="fleetmap">
      {/*
        그림 요약을 접근성 트리에 싣는다 — 지도는 캔버스라 화면 낭독이 읽을 것이
        없다. 결측도 여기 넣는다(`missingPositionAria`): 눈으로 보는 쪽에만 있으면
        낭독으로는 빠진 것이 없는 것처럼 들린다.
      */}
      <div
        className="fleetmap__canvas"
        ref={setCanvas}
        role="img"
        aria-label={
          ariaLabel ??
          `선박 ${shown}척의 현재 위치 지도.${missingPositionAria(vessels.length, shown)}`
        }
      />
      {missingText === null ? null : (
        <p className="fleetmap__missing">{missingText}</p>
      )}
      {/* 서버가 선을 주지 못했다 — 대권선으로 되돌리지 않고 그 사실을 적는다 (`#1300`). */}
      {routeFailure === null ? null : <p className="fleetmap__missing">{routeFailure}</p>}
      {/*
        읽는 법 (`#1052` ⓥ · 2026-09-18 확정).

        **범례를 따로 두지 않는다.** 마커마다 등급 문자가 붙어 있고, 같은 화면 위쪽
        「등급 분포」가 색↔문자 대응을 이미 보여 준다 — 범례를 더하면 같은 대응이
        화면에 세 번 적힌다.

        스스로 설명되지 않는 표식은 **굵은 테두리 하나**뿐이라 이 문장이 받는다.

        ## 세 문장에서 두 문장으로 (#1421)

        첫 문장 「확대·축소로 위치를 확인할 수 있습니다」는 **지도라면 누구나 하는 조작**을
        적은 것이라 뺐다. 남긴 둘은 뺄 수 없다 — 점선이 육지를 가로지르는 이유(`#1275`)와
        굵은 테두리의 뜻(`§9.5` 🔒)은 그림이 스스로 말하지 못한다.

        ⚠️ 「테두리가 굵은 **표**」는 오타였다(`PositionChart`는 「배」로 적는다).

        ## 「최단 경로일 뿐」에서 「경로망 위의 경로」로 (#1300)

        선이 대권선이 아니라 공개 해상 경로망(Eurostat SeaRoute)의 바닷길이 됐으므로
        「육지를 가로지를 수 있다」는 더 이상 사실이 아니다. 대신 **실제 항해 계획이
        아니라는 것**을 말한다 — 경로망은 운항 계획·수심·기상을 모른다.
      */}
      <p className="fleetmap__hint">
        {caption ?? (
          <>
            점선은 공개 해상 경로망 위의 경로입니다 — <b>실제 항해 계획이 아닙니다.</b>{' '}
            <b>테두리가 굵은 배</b>는 주의 대상입니다.
          </>
        )}
      </p>
    </div>
  )
}
