import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from '../../../../fleet/basemap'
import { routeGeometryAtProgress } from './routeGeometry'
import 'maplibre-gl/dist/maplibre-gl.css'
import './style.css'

type Coordinate = [number, number]
type RouteFixture = {
  metadata: { source: string; license: string; attribution: string; description: string }
  coordinates: Coordinate[]
  lengthNm: number
}

const root = document.getElementById('root')
if (!root) throw new Error('항로 실험 화면의 root 요소가 없습니다.')
root.innerHTML = `
  <main class="experience">
    <div class="map-host" aria-label="부산에서 싱가포르까지의 실험 해상 항로 지도"></div>
    <iframe class="harbor-frame" title="3D 항만 미니어처 지도" loading="lazy"></iframe>
    <div class="topline"><span class="brand">BlueLog ✦</span><span class="mode">3D globe voyage</span></div>
    <div class="status" role="status">해상 항로를 불러오는 중</div>
    <section class="panel" aria-label="항로 소개">
      <div class="eyebrow">Voyage overview · Harbor study</div>
      <h1>지구 위 항로를 따라 항만으로</h1>
      <p>곡면 지구 위 부산–싱가포르 공개 해상 경로망 예시입니다.<br>선박을 추적하고 양쪽 항만의 3D 장면으로 전환할 수 있습니다.</p>
      <div class="ports"><span>부산</span><i aria-hidden="true"></i><span>싱가포르</span></div>
      <div class="actions">
        <button class="primary enter-busan" type="button" disabled>부산 3D</button>
        <button class="primary enter-singapore" type="button" disabled>싱가포르 3D</button>
        <button class="secondary follow" type="button" disabled aria-pressed="false">선박 추적</button>
        <button class="secondary reset" type="button" disabled>전체 항로</button>
      </div>
      <div class="note">실험용 예시 항로이며 연간 시뮬레이션의 실제 항차가 아닙니다. 선은 표시용으로, CII 계산 거리에 사용하지 않습니다.</div>
    </section>
    <button class="back" type="button">← 전체 항로로 돌아가기</button>
    <div class="attribution">© OpenStreetMap contributors · Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)</div>
  </main>`

const experience = root.querySelector<HTMLElement>('.experience')!
const host = root.querySelector<HTMLElement>('.map-host')!
const frame = root.querySelector<HTMLIFrameElement>('.harbor-frame')!
const status = root.querySelector<HTMLElement>('.status')!
const enterBusan = root.querySelector<HTMLButtonElement>('.enter-busan')!
const enterSingapore = root.querySelector<HTMLButtonElement>('.enter-singapore')!
const follow = root.querySelector<HTMLButtonElement>('.follow')!
const reset = root.querySelector<HTMLButtonElement>('.reset')!
const back = root.querySelector<HTMLButtonElement>('.back')!

type Port = 'busan' | 'singapore'
const portLabels: Record<Port, string> = { busan: '부산 북항', singapore: '싱가포르 항만' }

function enterHarbor(port: Port) {
  frame.title = `${portLabels[port]} 3D 미니어처 지도`
  frame.src = `/experiment-3d.html?port=${port}`
  experience.classList.add('harbor')
}

function validRoute(value: unknown): value is RouteFixture {
  if (!value || typeof value !== 'object') return false
  const route = value as Partial<RouteFixture>
  return Array.isArray(route.coordinates) && route.coordinates.length >= 2 &&
    route.coordinates.every(point => Array.isArray(point) && point.length === 2 &&
      point.every(Number.isFinite) && point[0] >= -180 && point[0] <= 180 && point[1] >= -90 && point[1] <= 90) &&
    !!route.metadata && typeof route.metadata.source === 'string'
}

async function mount() {
  if (!await hasBasemap()) throw new Error('오프라인 세계 지도 자산을 찾을 수 없습니다.')
  const response = await fetch('/harbor/busan-singapore-searoute.json')
  if (!response.ok) throw new Error(`해상 항로 예시 데이터를 불러오지 못했습니다 (HTTP ${response.status}).`)
  const body: unknown = await response.json()
  if (!validRoute(body)) throw new Error('해상 항로 예시 데이터 형식이 올바르지 않습니다.')
  const route = body

  const registry = globalThis as { __bluelogPmtiles?: Protocol }
  if (!registry.__bluelogPmtiles) {
    const protocol = new Protocol()
    maplibregl.addProtocol('pmtiles', protocol.tile)
    registry.__bluelogPmtiles = protocol
  }
  const map = new maplibregl.Map({
    container: host,
    style: {
      version: 8,
      glyphs: `${BASEMAP_FONTS_URL}/{fontstack}/{range}.pbf`,
      sources: {
        protomaps: { type: 'vector', url: `pmtiles://${BASEMAP_URL}`, attribution: '© OpenStreetMap contributors' },
      },
      layers: layers('protomaps', namedFlavor('light'), { lang: 'ko' }),
    },
    center: [116, 19],
    zoom: 3,
    maxZoom: MAX_ZOOM,
    pitch: 38,
    bearing: -10,
    attributionControl: false,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.once('load', () => {
    map.setProjection({ type: 'globe' })
    map.setSky({
      'sky-color': '#b8d7de',
      'horizon-color': '#eff2e5',
      'fog-color': '#dbe6df',
      'sky-horizon-blend': 0.65,
      'horizon-fog-blend': 0.45,
      'fog-ground-blend': 0.55,
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0],
    })
    map.addSource('route', { type: 'geojson', data: {
      type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: route.coordinates },
    } })
    map.addSource('traveled', { type: 'geojson', data: {
      type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [route.coordinates[0], route.coordinates[0]] },
    } })
    map.addLayer({ id: 'route-halo', source: 'route', type: 'line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fffdf3', 'line-width': 10, 'line-opacity': .88 } })
    map.addLayer({ id: 'route-line', source: 'route', type: 'line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#347e87', 'line-width': 5 } })
    map.addLayer({ id: 'traveled-line', source: 'traveled', type: 'line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#f5c982', 'line-width': 5, 'line-opacity': .96 } })
    const bounds = new maplibregl.LngLatBounds()
    route.coordinates.forEach(point => bounds.extend(point))
    const showWholeRoute = () => map.fitBounds(bounds, {
      padding: innerWidth <= 650
        ? { top: 85, bottom: 345, left: 25, right: 25 }
        : { top: 105, bottom: 110, left: Math.min(520, innerWidth * .38), right: 60 },
      maxZoom: 4.5,
      pitch: 38,
      bearing: -10,
      duration: 850,
    })
    showWholeRoute()
    reset.disabled = false
    enterBusan.disabled = false
    enterSingapore.disabled = false
    follow.disabled = false
    enterBusan.addEventListener('click', () => enterHarbor('busan'))
    enterSingapore.addEventListener('click', () => enterHarbor('singapore'))
    back.addEventListener('click', () => {
      experience.classList.remove('harbor')
      frame.src = 'about:blank'
      map.resize()
      showWholeRoute()
    })
    const makePortMarker = (port: Port, coordinate: Coordinate, kind: string) => {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = `port-marker port-marker--${port}`
      button.innerHTML = `<span>${kind}</span><strong>${portLabels[port]}</strong>`
      button.setAttribute('aria-label', `${portLabels[port]} 3D 장면 열기`)
      button.addEventListener('click', () => enterHarbor(port))
      const anchor = port === 'busan' ? 'bottom-right' : 'bottom-left'
      return new maplibregl.Marker({ element: button, anchor }).setLngLat(coordinate).addTo(map)
    }
    const portMarkers = [
      makePortMarker('busan', route.coordinates[0], '출발'),
      makePortMarker('singapore', route.coordinates.at(-1)!, '도착'),
    ]
    const ship = document.createElement('div')
    ship.className = 'ship-marker'
    ship.setAttribute('role', 'img')
    ship.setAttribute('aria-label', '예시 해상 항로를 이동하는 선박')
    ship.innerHTML = `
      <svg class="ship-marker__vessel" viewBox="0 0 88 108" aria-hidden="true">
        <path class="ship-marker__wake" d="M27 84 17 102M44 88v17M61 84l10 18" />
        <path class="ship-marker__hull-shadow" d="M44 9 66 31 64 75 55 91 33 91 24 75 22 31Z" />
        <path class="ship-marker__hull" d="M44 5 63 27 61 74 54 87 34 87 27 74 25 27Z" />
        <path class="ship-marker__deck" d="M44 13 56 29 55 75 51 81 37 81 33 75 32 29Z" />
        <path class="ship-marker__bow" d="M44 13 55 28H33Z" />
        <rect class="ship-marker__cabin" x="35" y="31" width="18" height="14" rx="2" />
        <rect class="ship-marker__window" x="38" y="34" width="12" height="4" rx="1" />
        <rect class="ship-marker__container ship-marker__container--one" x="35" y="48" width="8" height="12" rx="1" />
        <rect class="ship-marker__container ship-marker__container--two" x="45" y="48" width="8" height="12" rx="1" />
        <rect class="ship-marker__container ship-marker__container--three" x="35" y="62" width="8" height="12" rx="1" />
        <rect class="ship-marker__container ship-marker__container--four" x="45" y="62" width="8" height="12" rx="1" />
      </svg>
      <span class="ship-marker__label">운항 중</span>`
    const vessel = ship.querySelector<SVGElement>('.ship-marker__vessel')!
    const marker = new maplibregl.Marker({ element: ship, anchor: 'center' }).setLngLat(route.coordinates[0]).addTo(map)
    const traveled = map.getSource('traveled') as maplibregl.GeoJSONSource
    const started = performance.now()
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
    let following = false
    let lastCameraUpdate = 0
    const setFollowing = (next: boolean) => {
      following = next && !reducedMotion
      follow.setAttribute('aria-pressed', String(following))
      follow.textContent = following ? '추적 중지' : '선박 추적'
    }
    follow.addEventListener('click', () => setFollowing(!following))
    reset.addEventListener('click', () => {
      setFollowing(false)
      showWholeRoute()
    })
    // 자동 추적의 easeTo도 zoomstart를 발생시키므로 직접 드래그·회전만 추적 해제로 본다.
    for (const eventName of ['dragstart', 'rotatestart'] as const) {
      map.on(eventName, () => setFollowing(false))
    }
    let frameId = 0
    let lastTrailUpdate = 0
    const animate = (time: number) => {
      const progress = reducedMotion ? .5 : ((time - started) % 24000) / 24000
      const geometry = routeGeometryAtProgress(route.coordinates, progress)
      const position: Coordinate = [geometry.position[0], geometry.position[1]]
      vessel.style.transform = `rotate(${geometry.bearing - map.getBearing()}deg)`
      marker.setLngLat(position)
      if (following && time - lastCameraUpdate >= 650) {
        map.easeTo({ center: position, zoom: Math.max(map.getZoom(), 5.2), pitch: 58, duration: 600, essential: false })
        lastCameraUpdate = time
      }
      if (time - lastTrailUpdate >= 100) {
        traveled.setData({
          type: 'Feature', properties: {},
          geometry: { type: 'LineString', coordinates: geometry.traveledCoordinates.map(point => [point[0], point[1]]) },
        })
        lastTrailUpdate = time
      }
      if (!reducedMotion) frameId = requestAnimationFrame(animate)
    }
    frameId = requestAnimationFrame(animate)
    addEventListener('pagehide', () => {
      cancelAnimationFrame(frameId)
      marker.remove()
      portMarkers.forEach(portMarker => portMarker.remove())
      map.remove()
    }, { once: true })
    status.textContent = `${route.coordinates.length}개 경로점 · 3D 지구 항로 · 부산·싱가포르 항만 전환 가능`
  })
  map.on('error', event => console.error('[route-overview] 지도 오류:', event.error))
}

void mount().catch(error => {
  status.textContent = error instanceof Error ? error.message : '항로 지도를 표시하지 못했습니다.'
  console.error('[route-overview] 실험 실패:', error)
})
