import { useEffect, useRef, useState, type ReactNode } from 'react'
import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import './FleetMap.css'
import type { FleetVessel } from './types'
import { BASEMAP_FONTS_URL, BASEMAP_URL, INITIAL_ZOOM, MAX_ZOOM } from './basemap'
import { greatCirclePath } from './greatCircle'
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
 */

/**
 * 선박과 무관하게 그리는 항로 하나 (`#1265`).
 *
 * 항로 비교(`UIFLOW 2-2`)가 쓴다 — 그 화면의 세 시나리오는 **같은 두 점을 공유**하고
 * 거리·속력만 다르므로(`PRD §11.3` 우회 = 직항 × 1.05) **그릴 경로는 하나뿐이다.**
 * 서버도 직항 거리를 이 두 점의 대권거리로 낸다(`PRD §11.2`) — 이 선은 표의
 * 「직항 거리」를 그대로 그린 것이지 장식이 아니다.
 */
export interface RouteLine {
  name: string
  departureLat: number
  departureLon: number
  arrivalLat: number
  arrivalLon: number
}

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
  for (const d of VESSEL_PATHS) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', d)
    svg.appendChild(path)
  }
  root.appendChild(svg)

  const label = document.createElement('span')
  label.className = 'fleetmap__badge'
  // 색 단독 금지 (`§14`). 등급이 없으면 「—」로 둔다 — 빈 칸은 「A」로 읽힌다.
  label.textContent = rating ?? '—'
  root.appendChild(label)

  root.setAttribute('role', 'img')
  root.setAttribute(
    'aria-label',
    `${vessel.name} · 등급 ${rating ?? '없음'}${isAtRisk(vessel) ? ' · 주의' : ''}`,
  )
  return root
}

/** 항로선 GeoJSON. 진행 중 항차가 있는 선박만 한 줄씩. */
function routeCollection(
  points: Placed[],
  extra: readonly RouteLine[],
): maplibregl.GeoJSONSourceSpecification['data'] {
  const fromProps = extra.flatMap((route) => {
    const coords = greatCirclePath(
      route.departureLat,
      route.departureLon,
      route.arrivalLat,
      route.arrivalLon,
    )
    if (coords.length < 2) return []
    return [
      {
        type: 'Feature' as const,
        properties: { name: route.name },
        geometry: { type: 'LineString' as const, coordinates: coords },
      },
    ]
  })

  return {
    type: 'FeatureCollection',
    features: points.flatMap(({ vessel }) => {
      const route = vessel.route
      if (route === null) return []
      const coords = greatCirclePath(
        Number(route.departureLat),
        Number(route.departureLon),
        Number(route.arrivalLat),
        Number(route.arrivalLon),
      )
      if (coords.length < 2) return []
      return [
        {
          type: 'Feature' as const,
          properties: { name: vessel.name },
          geometry: { type: 'LineString' as const, coordinates: coords },
        },
      ]
    }).concat(fromProps),
  }
}

export function FleetMap({ vessels, routes = NO_ROUTES, ariaLabel, caption }: FleetMapProps) {
  /*
   * 좌표가 없는 선박은 `placed()`에서 **조용히 빠진다** (#1103).
   *
   * 개략도(`PositionChart`)는 몇 척이 빠졌는지 적는데 이 지도만 아무 말도 하지
   * 않았다 — 4척 중 1척이 미입력이면 지도에 3척만 그려지고 **그 3척이 선대 전부로**
   * 읽힌다. 문구는 개략도와 **같은 원천**(`fleetRules`)을 쓴다.
   */
  const shown = placed(vessels).length
  const missingText = missingPositionText(vessels.length, shown)

  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (container.current === null || map.current !== null) return

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
      container: container.current,
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
      setReady(false)
    }
  }, [])

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

    const collection = routeCollection(points, routes)
    const source = instance.getSource('routes') as maplibregl.GeoJSONSource | undefined
    if (source === undefined) {
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
       */
      const accent = getComputedStyle(document.documentElement)
        .getPropertyValue('--semantic-info')
        .trim()

      instance.addSource('routes', { type: 'geojson', data: collection })
      instance.addLayer({
        id: 'routes',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          ...(accent === '' ? {} : { 'line-color': accent }),
          'line-width': 2,
          // 파선이라 색을 못 봐도 배경의 도로·경계선과 구분된다 (`§14`).
          'line-dasharray': [2, 1.5],
          'line-opacity': 0.9,
        },
      })
    } else {
      source.setData(collection)
    }

    // 처음 한 번만 그려진 것에 맞춘다 — 갱신마다 맞추면 사용자가 확대해 둔 자리가 튄다.
    if ((points.length > 0 || routes.length > 0) && instance.getZoom() === INITIAL_ZOOM) {
      const bounds = new maplibregl.LngLatBounds()
      for (const { lat, lon } of points) bounds.extend([lon, lat])
      /*
       * 명시 경로의 **양 끝도** 넣는다 (`#1265`).
       *
       * 종전 조건은 `points.length > 0`이라 **선박이 없는 화면에서는 아예 돌지 않았다.**
       * 항로 비교는 선박을 그리지 않으므로 지도가 기본 뷰(`INITIAL_ZOOM`)에 머물고,
       * 그린 선이 **화면 밖에 있을 수 있다** — 지도는 떴는데 항로만 안 보이는 상태가 된다.
       */
      for (const route of routes) {
        bounds.extend([route.departureLon, route.departureLat])
        bounds.extend([route.arrivalLon, route.arrivalLat])
      }
      instance.fitBounds(bounds, { padding: 48, maxZoom: 6, animate: false })
    }
  }, [vessels, routes, ready])

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
        ref={container}
        role="img"
        aria-label={
          ariaLabel ??
          `선박 ${shown}척의 현재 위치 지도.${missingPositionAria(vessels.length, shown)}`
        }
      />
      {missingText === null ? null : (
        <p className="fleetmap__missing">{missingText}</p>
      )}
      {/*
        읽는 법 (`#1052` ⓥ · 2026-09-18 확정).

        **범례를 따로 두지 않는다.** 마커마다 등급 문자가 붙어 있고, 같은 화면 위쪽
        「등급 분포」가 색↔문자 대응을 이미 보여 준다 — 범례를 더하면 같은 대응이
        화면에 세 번 적힌다.

        스스로 설명되지 않는 표식은 **굵은 테두리 하나**뿐이라 이 문장이 받는다.

        ⚠️ **「해협·수심·기상을 피해 갑니다」로는 모자랐다** (`#1265`). 그 문안은 선이
        대체로 바다 위를 지나되 조금 돌아간다는 뜻으로 읽힌다. 실제로는 대륙간 구간에서
        **육지를 통째로 가로지른다** — 상하이→로테르담의 대권은 시베리아를 지나며
        실제 항로의 **46%** 길이다(`greatCircle.ts`). 항로선이 그려지지 않던 동안에는
        아무도 보지 못했고, 그려지기 시작하자 **고장으로 읽혔다.**

        항로 비교 화면이 좌표 기반 거리에 붙이는 고지(「운하·해협을 돌아가는 실제
        항로보다 짧을 수 있습니다」)와 같은 수준으로 맞춘다.
      */}
      <p className="fleetmap__hint">
        {caption ?? (
          <>
            <b>확대·축소로 위치를 확인할 수 있습니다.</b> 점선은 두 항을 잇는 <b>최단 경로</b>일 뿐
            예상 항로가 아닙니다 — 육지를 가로지를 수 있고, 운하·해협을 도는 실제 항로는
            이보다 훨씬 깁니다. 테두리가 굵은 표는 주의 대상입니다.
          </>
        )}
      </p>
    </div>
  )
}
