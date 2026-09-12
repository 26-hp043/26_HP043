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
import { isAtRisk } from './fleetRules'

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
      // CSS 변수는 지도 페인트가 읽지 못한다 — 계산된 값을 꺼내 넣는다.
      const accent = getComputedStyle(document.documentElement)
        .getPropertyValue('--semantic-info')
        .trim()
      instance.setPaintProperty('routes', 'line-color', accent === '' ? '#1f6feb' : accent)
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

  return (
    <div className="fleetmap">
      <div className="fleetmap__canvas" ref={container} />
      <p className="fleetmap__hint">
        <b>확대·축소로 위치를 확인할 수 있습니다.</b> 점선은 진행 중 항차의 최단 경로이며,
        실제 항해는 해협·수심·기상을 피해 갑니다.
      </p>
    </div>
  )
}
