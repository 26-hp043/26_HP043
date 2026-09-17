import { useEffect, useRef, useState } from 'react'
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

interface FleetMapProps {
  vessels: FleetVessel[]
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
function routeCollection(points: Placed[]): maplibregl.GeoJSONSourceSpecification['data'] {
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
    }),
  }
}

export function FleetMap({ vessels }: FleetMapProps) {
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

    const collection = routeCollection(points)
    const source = instance.getSource('routes') as maplibregl.GeoJSONSource | undefined
    if (source === undefined) {
      instance.addSource('routes', { type: 'geojson', data: collection })
      instance.addLayer({
        id: 'routes',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': 'var-replaced-at-runtime',
          'line-width': 2,
          // 파선이라 색을 못 봐도 배경의 도로·경계선과 구분된다 (`§14`).
          'line-dasharray': [2, 1.5],
          'line-opacity': 0.9,
        },
      })
      /*
       * CSS 변수는 지도 페인트가 읽지 못한다 — 계산된 값을 꺼내 넣는다.
       *
       * ⚠️ 종전에는 못 읽었을 때 리터럴 `#1f6feb`로 떨어지게 두었는데,
       * **`--semantic-info`가 존재한 적이 없어 그 리터럴이 언제나 실제 색이었다**
       * (`#1052` 조사). `§9.5` 🔒가 정한 토큰이 지켜지지 않았고, 저장소에서 토큰 밖
       * 색을 쓰는 유일한 지점이었으며, 라이트·다크가 같은 파랑이었다.
       *
       * `#1022`가 Figma 세트에 Info를 들여 그 토큰이 실재하게 됐다. **리터럴을
       * 남기지 않는다** — 남기면 다음에 토큰이 사라져도 또 조용히 그 값으로 간다.
       * 빈 값이면 페인트를 건드리지 않고 두어, 어긋남이 눈에 띄게 한다.
       */
      const accent = getComputedStyle(document.documentElement)
        .getPropertyValue('--semantic-info')
        .trim()
      if (accent !== '') instance.setPaintProperty('routes', 'line-color', accent)
    } else {
      source.setData(collection)
    }

    // 처음 한 번만 선대에 맞춘다 — 갱신마다 맞추면 사용자가 확대해 둔 자리가 튄다.
    if (points.length > 0 && instance.getZoom() === INITIAL_ZOOM) {
      const bounds = new maplibregl.LngLatBounds()
      for (const { lat, lon } of points) bounds.extend([lon, lat])
      instance.fitBounds(bounds, { padding: 48, maxZoom: 6, animate: false })
    }
  }, [vessels, ready])

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
        aria-label={`선박 ${shown}척의 현재 위치 지도.${missingPositionAria(vessels.length, shown)}`}
      />
      {missingText === null ? null : (
        <p className="fleetmap__missing">{missingText}</p>
      )}
      <p className="fleetmap__hint">
        <b>확대·축소로 위치를 확인할 수 있습니다.</b> 점선은 진행 중 항차의 최단 경로이며,
        실제 항해는 해협·수심·기상을 피해 갑니다.
      </p>
    </div>
  )
}
