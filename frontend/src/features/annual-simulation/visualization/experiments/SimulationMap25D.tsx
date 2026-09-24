import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from '../../../fleet/basemap'
import { fetchSeaRoute, type SeaRouteRequest } from '../../../fleet/seaRoute'
import type { MapCoordinate } from '../model'

type ExperimentalRoute =
  | { readonly source: 'sea-route'; readonly request: SeaRouteRequest }
  | { readonly source: 'experiment'; readonly coordinates: readonly MapCoordinate[] }

interface SimulationMap25DProps {
  /** 실험 전용 입력. 연간 시뮬레이션 결과에 좌표가 있다는 뜻이 아니다. */
  route: ExperimentalRoute
}

type Status = 'checking' | 'loading' | 'ready' | 'asset-missing' | 'webgl-unavailable' | 'route-failed' | 'map-failed'

const EMPTY_ROUTE: maplibregl.GeoJSONSourceSpecification['data'] = {
  type: 'FeatureCollection',
  features: [],
}

/** 경로의 각 구간 길이를 사용해 마커가 일정한 지상 속도로 움직이게 한다. */
function routePosition(coordinates: readonly MapCoordinate[], progress: number): [number, number] {
  if (coordinates.length < 2) throw new Error('경로에는 좌표가 둘 이상 필요합니다.')
  const lengths = coordinates.slice(1).map(([lon, lat], index) => {
    const [prevLon, prevLat] = coordinates[index]
    const dLat = ((lat - prevLat) * Math.PI) / 180
    const dLon = (((lon - prevLon + 540) % 360) - 180) * Math.PI / 180
    const a = Math.sin(dLat / 2) ** 2 + Math.cos((prevLat * Math.PI) / 180) *
      Math.cos((lat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2
    return 2 * Math.asin(Math.min(1, Math.sqrt(a)))
  })
  const total = lengths.reduce((sum, length) => sum + length, 0)
  if (total === 0) return [...coordinates[0]]
  let remaining = Math.max(0, Math.min(1, progress)) * total
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index]
    if (remaining <= length || index === lengths.length - 1) {
      const fraction = length === 0 ? 0 : remaining / length
      const [startLon, startLat] = coordinates[index]
      const [endLon, endLat] = coordinates[index + 1]
      const shortLon = ((endLon - startLon + 540) % 360) - 180
      return [startLon + shortLon * fraction, startLat + (endLat - startLat) * fraction]
    }
    remaining -= length
  }
  return [...coordinates[coordinates.length - 1]]
}

function validCoordinates(coordinates: readonly MapCoordinate[]): boolean {
  return coordinates.length >= 2 && coordinates.every(
    ([lon, lat]) => Number.isFinite(lon) && Number.isFinite(lat) &&
      lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90,
  )
}

/** #1431: 서비스 화면에 연결하지 않은 MapLibre 2.5D 실험. */
export function SimulationMap25D({ route }: SimulationMap25DProps) {
  const container = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('checking')
  const [bearing, setBearing] = useState(0)
  const [pitch, setPitch] = useState(50)
  const map = useRef<maplibregl.Map | null>(null)
  const routeKey = route.source === 'sea-route'
    ? JSON.stringify(route.request)
    : JSON.stringify(route.coordinates)

  useEffect(() => {
    let disposed = false
    let frame = 0
    let marker: maplibregl.Marker | null = null
    let instance: maplibregl.Map | null = null

    async function mount() {
      setStatus('checking')
      if (!await hasBasemap()) {
        if (!disposed) setStatus('asset-missing')
        return
      }
      if (disposed) return

      // MapLibre는 WebGL 생성 실패 시 생성자에서 던지거나 `error` 이벤트를 보낸다.
      const probe = document.createElement('canvas')
      if (!probe.getContext('webgl2') && !probe.getContext('webgl')) {
        setStatus('webgl-unavailable')
        return
      }
      const host = container.current
      if (!host) return

      try {
        const registry = globalThis as { __bluelogPmtiles?: Protocol }
        if (registry.__bluelogPmtiles === undefined) {
          const protocol = new Protocol()
          maplibregl.addProtocol('pmtiles', protocol.tile)
          registry.__bluelogPmtiles = protocol
        }
        instance = new maplibregl.Map({
          container: host,
          style: {
            version: 8,
            glyphs: `${BASEMAP_FONTS_URL}/{fontstack}/{range}.pbf`,
            sources: {
              protomaps: {
                type: 'vector',
                url: `pmtiles://${BASEMAP_URL}`,
                attribution: '© OpenStreetMap',
              },
              experimentRoute: { type: 'geojson', data: EMPTY_ROUTE },
            },
            layers: layers('protomaps', namedFlavor('light'), { lang: 'ko' }),
          },
          center: [125, 22],
          zoom: 3,
          maxZoom: MAX_ZOOM,
          pitch: 50,
          maxPitch: 55,
          dragRotate: true,
          pitchWithRotate: true,
          touchZoomRotate: true,
          attributionControl: { compact: true },
        })
        map.current = instance
        instance.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
        instance.on('error', (event) => {
          if (disposed) return
          console.error('[SimulationMap25D] 지도 오류:', event.error)
          setStatus('map-failed')
        })
        instance.on('rotate', () => {
          if (!disposed) setBearing(Math.round(instance!.getBearing()))
        })
        instance.on('pitch', () => {
          if (!disposed) setPitch(Math.round(instance!.getPitch()))
        })
        setStatus('loading')

        let coordinates: readonly MapCoordinate[]
        try {
          coordinates = route.source === 'sea-route'
            ? (await fetchSeaRoute(route.request)).coordinates
            : route.coordinates
        } catch (error) {
          if (!disposed) {
            console.error('[SimulationMap25D] 해상 항로 조회 실패:', error)
            setStatus('route-failed')
          }
          return
        }
        if (disposed) return
        if (!validCoordinates(coordinates)) throw new Error('경로 좌표가 유효하지 않습니다.')
        await new Promise<void>((resolve, reject) => {
          if (instance!.loaded()) resolve()
          else {
            instance!.once('load', () => resolve())
            instance!.once('error', (event) => reject(event.error))
          }
        })
        if (disposed) return
        const source = instance.getSource('experimentRoute') as maplibregl.GeoJSONSource
        source.setData({
          type: 'Feature',
          properties: {},
          geometry: { type: 'LineString', coordinates: coordinates.map(([lon, lat]) => [lon, lat]) },
        })
        instance.addLayer({
          id: 'experimentRoute', type: 'line', source: 'experimentRoute',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#1763a6', 'line-width': 4, 'line-opacity': 0.9 },
        })
        const bounds = new maplibregl.LngLatBounds()
        for (const coordinate of coordinates) bounds.extend([...coordinate])
        instance.fitBounds(bounds, { padding: 90, maxZoom: 4.5, pitch: 50, bearing: 0, animate: false })

        const ship = document.createElement('span')
        ship.textContent = '◆'
        ship.style.cssText = 'font-size:24px;color:#063a66;text-shadow:0 0 3px white'
        ship.setAttribute('role', 'img')
        ship.setAttribute('aria-label', '실험 항로의 이동 선박')
        marker = new maplibregl.Marker({ element: ship, anchor: 'center' })
          .setLngLat([...coordinates[0]]).addTo(instance)
        const started = performance.now()
        const animate = (now: number) => {
          if (disposed || !marker) return
          marker.setLngLat(routePosition(coordinates, ((now - started) % 18000) / 18000))
          frame = requestAnimationFrame(animate)
        }
        frame = requestAnimationFrame(animate)
        setStatus('ready')
      } catch (error) {
        if (!disposed) {
          console.error('[SimulationMap25D] 실험 실패:', error)
          setStatus('map-failed')
        }
      }
    }
    void mount()

    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      marker?.remove()
      instance?.remove()
      if (map.current === instance) map.current = null
    }
    // 직렬화한 입력이 바뀔 때만 새 지도를 만든다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey, route.source])

  const statusText: Record<Status, string> = {
    checking: '지도 자산 확인 중', loading: '지도와 항로 로딩 중', ready: '지도와 이동 선박 표시 중',
    'asset-missing': 'PMTiles 지도 자산이 없거나 Range 요청을 지원하지 않습니다.',
    'webgl-unavailable': '이 브라우저에서 WebGL을 사용할 수 없습니다.',
    'route-failed': '해상 항로를 조회하지 못했습니다. 항로와 선박은 표시하지 않습니다.',
    'map-failed': '지도를 표시하지 못했습니다. 브라우저 콘솔을 확인하세요.',
  }

  return (
    <section aria-label="2.5D 지도 렌더링 실험" style={{ width: '100%' }}>
      <p data-testid="route-source">
        {route.source === 'experiment'
          ? '실험 좌표 · 연간 시뮬레이션 결과의 실제 항차가 아닙니다.'
          : 'SeaRoute API 조회 좌표 · 연간 시뮬레이션 결과의 실제 항차가 아닙니다.'}
      </p>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" onClick={() => map.current?.rotateTo(map.current.getBearing() - 30)} disabled={status !== 'ready'} aria-describedby="route-controls-status">왼쪽 회전</button>
        <button type="button" onClick={() => map.current?.rotateTo(map.current.getBearing() + 30)} disabled={status !== 'ready'} aria-describedby="route-controls-status">오른쪽 회전</button>
        <label>기울기 <input type="range" min="45" max="55" value={pitch} onChange={(event) => map.current?.setPitch(Number(event.target.value))} disabled={status !== 'ready'} /></label>
        <output>pitch {pitch}° · bearing {bearing}°</output>
      </div>
      <p role="status" id="route-controls-status" data-testid="map-status">{statusText[status]}</p>
      <div ref={container} role="region" aria-label="항로 지도. 드래그로 이동, 오른쪽 드래그로 회전, 휠로 확대합니다." style={{ height: 560, width: '100%', background: '#dbe8ef' }} />
    </section>
  )
}
