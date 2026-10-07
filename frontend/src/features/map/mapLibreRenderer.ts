import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import { BASEMAP_FONTS_URL, BASEMAP_URL, INITIAL_ZOOM, MAX_ZOOM } from '../fleet/basemap'
import type { MapRenderer, MapRendererEvent } from './renderer'
import { routeStyle } from './routeStyles'
import { mergePortMarkers, portLabelPlacement, portMarkerElement, type PortMarkerModel } from './portMarkers'
import './MapMarkers.css'
import { ensureMapLibreWorker } from './mapLibreWorker'
import { mapQualityPolicy, type MapQualityTier } from './quality'
import {
  ProjectionToggleControl,
  readProjectionPreference,
  writeProjectionPreference,
  type MapProjection,
} from './projectionToggle'
import type { GlobeVesselLayerController } from './vesselLayer'
import type { GlobeVesselModel } from './vesselModel'

interface MapLibreMarkerModel {
  readonly coordinate: readonly [number, number]
  readonly element: HTMLElement
}

interface MapLibreRouteModel {
  readonly data: maplibregl.GeoJSONSourceSpecification['data']
  readonly attribution: string
  readonly bounds: readonly (readonly [number, number])[]
}

/**
 * 「이 배를 보여 달라」 (#1831).
 *
 * 좌측 패널의 행에서 배를 고르면 지도가 **그 배로 옮겨 간 뒤** 카드가 열려야 한다 —
 * 화면 밖의 마커에 카드만 뜨면 무엇에 붙은 카드인지 알 수 없다. 그래서 옮기는 일과
 * 「열어라」를 한 길로 묶어, 멈춘 뒤 `selection`을 낸다. 마커를 직접 누른 경우도 같은
 * `selection`으로 들어오므로 **두 입구가 한 길**이다.
 *
 * `nonce`가 신호인 것은 **같은 배를 다시 고를 수 있기** 때문이다 — id만 보면 두 번째
 * 누름이 아무 일도 하지 않는다.
 */
interface MapFocusModel {
  readonly id: string
  readonly coordinate: readonly [number, number]
  readonly nonce: number
}

export interface MapLibreMapModel {
  readonly mode: 'fleet' | 'comparison'
  readonly markers: readonly MapLibreMarkerModel[]
  readonly routes: MapLibreRouteModel
  readonly ports: readonly PortMarkerModel[]
  readonly vessels?: readonly GlobeVesselModel[]
  readonly qualityTier?: MapQualityTier
  /** 「이 배를 보여 달라」 (#1831). 생략하면 아무 일도 하지 않는다. */
  readonly focus?: MapFocusModel | null
  /**
   * 항로 비교에서 한 노선을 앞으로 (10/7) — 고른 쪽은 그대로 · 굵게, 나머지는 흐리게. `null` ·
   * 생략이면 둘 다 기본 모양이다.
   */
  readonly highlight?: 'DIRECT' | 'DETOUR' | 'SLOW' | null
}

function ensureProtocol(): void {
  // 워커 주소를 지도보다 먼저 정한다 — 풀이 뜬 뒤에는 바꿔도 소용이 없다 (`#1909`).
  ensureMapLibreWorker()
  const registry = globalThis as { __bluelogPmtiles?: Protocol }
  if (registry.__bluelogPmtiles === undefined) {
    const protocol = new Protocol()
    maplibregl.addProtocol('pmtiles', protocol.tile)
    registry.__bluelogPmtiles = protocol
  }
}

function createMap(
  target: HTMLElement,
  attribution: string,
  emit: (event: MapRendererEvent) => void,
  globe: boolean,
): maplibregl.Map {
  ensureProtocol()
  const map = new maplibregl.Map({
    container: target,
    style: {
      version: 8,
      glyphs: `${BASEMAP_FONTS_URL}/{fontstack}/{range}.pbf`,
      sources: {
        protomaps: {
          type: 'vector', url: `pmtiles://${BASEMAP_URL}`, attribution: '© OpenStreetMap',
        },
        routes: {
          type: 'geojson', data: { type: 'FeatureCollection', features: [] }, attribution,
        },
      },
      layers: layers('protomaps', namedFlavor('light'), { lang: 'ko' }),
    },
    center: [127, 30], zoom: INITIAL_ZOOM, maxZoom: MAX_ZOOM,
    pitch: globe ? GLOBE_PITCH : 0,
    dragRotate: globe, pitchWithRotate: globe, touchZoomRotate: globe,
    // #1853 ③ (2026-09-27 디자인 확정) — 출처를 **접힌 컨트롤에서 꺼내** 지도 아래 한 줄로 둔다
    // (`RouteSourceNotice`). 컨트롤(`compact`)은 지도를 한 번 끌면 접혀 ⓘ를 눌러야 보였다 —
    // 라이선스 표기(EUPL-1.2 · Apache-2.0 · ODbL)를 그 자리에 두면 표기했다고 보기 어렵다.
    attributionControl: false,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right')
  map.on('error', (event) => {
    console.error('[MapLibreRenderer] 지도 오류:', event.error?.message ?? String(event))
    const error = event.error instanceof Error
      ? event.error
      : new Error(event.error?.message ?? String(event))
    emit({ type: 'error', error })
  })
  return map
}

/** 지구본일 때 처음 기울기 — 평면에서는 0(위에서 내려다본다). */
const GLOBE_PITCH = 18

/**
 * 지도를 **덮는** 오버레이임을 지도에게 알리는 표시 (#2051).
 *
 * ## 왜 있어야 하나
 *
 * 대시보드의 선박 패널은 `position: absolute`로 지도 **위에** 뜬다 — 지도의 레이아웃
 * 폭에는 잡히지 않는다. 그래서 지도는 캔버스 전체를 쓸 수 있다고 믿고 그 한가운데에
 * 선박을 놓는데, **그 한가운데의 왼쪽 절반이 패널 밑에 깔린다.** 실제로 선박 다섯이
 * 오른쪽 끝에 점으로 뭉쳤다.
 *
 * `DESIGN_SYSTEM §9.5`(v2.28)가 「오버레이는 지도의 일부다」라고 정했다. 그 말대로라면
 * **범위를 잡을 때도 지도의 일부로 세야** 한다.
 *
 * ## 왜 클래스 이름을 보지 않나
 *
 * 이 계층은 제품 화면을 모른다 — `.fleet__panel`을 여기서 읽으면 지도 어댑터가
 * 대시보드를 아는 셈이 되고, `architecture.test.ts`가 지키는 방향과 반대다. 대신
 * **지도가 표시를 하나 정의하고** 덮는 쪽이 그것을 단다.
 */
const MAP_OVERLAY_ATTRIBUTE = 'data-map-overlay'

/**
 * 오버레이가 지도의 **왼쪽에서** 가리는 폭(px).
 *
 * 숫자를 새로 적지 않는다 — 폭은 CSS가 갖고 있고 여기서는 **실제 요소를 잰다.**
 * 그래서 세 경우가 저절로 맞는다.
 *
 * - 패널이 접히면 그 사각형이 작아져 가리는 폭도 줄어든다
 * - 좁은 화면(1100 이하)에서 패널이 지도 **아래**로 내려가면 세로로 겹치지 않아 0이다
 * - 패널 폭이 바뀌어도 따라온다
 *
 * jsdom은 배치를 계산하지 않아 사각형이 전부 0이다 — 그때는 0을 돌려주어 종전과
 * 같은 값이 된다. 검사는 사각형을 세워 두고 확인한다.
 */
function overlayInsetStart(target: HTMLElement): number {
  const documentRef = target.ownerDocument
  if (!documentRef || typeof target.getBoundingClientRect !== 'function') return 0
  const map = target.getBoundingClientRect()
  if (map.width <= 0 || map.height <= 0) return 0
  let inset = 0
  for (const overlay of documentRef.querySelectorAll<HTMLElement>(`[${MAP_OVERLAY_ATTRIBUTE}]`)) {
    const rect = overlay.getBoundingClientRect()
    // 세로로 겹치지 않으면 지도를 가리지 않는다 — 패널이 지도 아래로 내려간 경우다.
    if (rect.bottom <= map.top || rect.top >= map.bottom) continue
    // 지도의 왼쪽 끝에서 오버레이의 오른쪽 끝까지가 가려진 띠다.
    const covered = rect.right - map.left
    if (covered > inset) inset = covered
  }
  /*
   * ⚠️ 절반을 넘기지 않는다. 이 값이 잘못 커지면 `fitBounds`가 들어갈 자리를 잃고
   * 지도가 엉뚱한 배율로 튄다 — 뭉쳐 보이는 것보다 나쁜 고장이다.
   */
  return Math.max(0, Math.min(inset, map.width / 2))
}

/** 날짜변경선을 사이에 둔 좌표를 지구 반대편까지 넓히지 않고 같은 연속 구간으로 푼다. */
function unwrapDateline(coordinates: readonly (readonly [number, number])[]): readonly (readonly [number, number])[] {
  if (coordinates.length < 2) return coordinates
  const normalized = coordinates.map(([lon]) => ((lon % 360) + 360) % 360).sort((a, b) => a - b)
  let largestGap = -1
  let start = normalized[0]
  for (let index = 0; index < normalized.length; index += 1) {
    const current = normalized[index]
    const next = index === normalized.length - 1 ? normalized[0] + 360 : normalized[index + 1]
    if (next - current > largestGap) {
      largestGap = next - current
      start = next % 360
    }
  }
  return coordinates.map(([lon, lat]) => {
    let unwrapped = ((lon % 360) + 360) % 360
    if (unwrapped < start) unwrapped += 360
    return [unwrapped, lat] as const
  })
}

/** Fleet와 Comparison이 함께 쓰는 MapLibre adapter. 제품 컴포넌트는 엔진을 import하지 않는다. */
export const mapLibreRenderer: MapRenderer<MapLibreMapModel> = {
  mount(target, initialModel, emit) {
    const quality = mapQualityPolicy({ override: initialModel.qualityTier })
    /*
     * 지구본 ↔ 평면 (`#1976`). `low` 기기는 지금처럼 평면만 — 버튼도 두지 않는다. 그 밖은
     * 사용자가 고른 방식, 고른 적이 없으면 **지구본**으로 연다(09-27 사용자 결정).
     */
    let projection: MapProjection = quality.globe ? readProjectionPreference() : 'mercator'
    /** 생성자가 기울기·회전을 정한 투영 — `load` 때 이것과 다르면 카메라를 맞춘다. */
    const constructedGlobe = projection === 'globe'
    const map = createMap(target, initialModel.routes.attribution, emit, constructedGlobe)
    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => map.resize())
    resizeObserver?.observe(target)
    let model = initialModel
    let ready = false
    let fitted = false
    /**
     * 카메라가 **이미 뜻을 갖고 놓였다** (#2051).
     *
     * ⚠️ 종전에는 `map.getZoom() === INITIAL_ZOOM`으로 이것을 대신했다 — **부동소수
     * 정확 비교**다. 데이터가 오기 전에 사용자가 지도를 한 번이라도 움직이면 조건이
     * 거짓이 되어 **범위 맞추기가 통째로 건너뛰어졌고**, 그때는 초기 `center: [127, 30]`
     * `zoom: 2`(인도~일본)에 그대로 남았다. 「아직 한 번도 안 맞췄다」는 위 `fitted`가
     * 이미 말하고 있으므로, 줌 비교가 보려던 것은 **사용자가 손댔는가**였다.
     *
     * 그 뜻을 그대로 적는다 — 사용자가 직접 움직였거나(`originalEvent`가 있는 카메라
     * 이동), 「이 배를 보여 달라」(#1831)로 옮겨 갔으면 더는 맞추지 않는다.
     */
    let cameraPlaced = false
    map.on('movestart', (event: { readonly originalEvent?: unknown }) => {
      // 프로그램이 옮긴 이동에는 `originalEvent`가 없다 — 그쪽은 아래 `focus`가 따로 센다.
      if (event?.originalEvent) cameraPlaced = true
    })
    let markers: maplibregl.Marker[] = []
    let portMarkers: maplibregl.Marker[] = []
    let vesselLayer: GlobeVesselLayerController | null = null
    let destroyed = false

    let renderedMarkers: readonly MapLibreMarkerModel[] | null = null
    let renderedPorts: readonly PortMarkerModel[] | null = null
    /** 이미 옮겨 간 `focus.nonce`. 같은 값으로 모델이 다시 와도 지도가 튀지 않는다 (#1831). */
    let focusedNonce: number | null = null
    const draw = () => {
      if (!ready) return
      // 항만을 먼저 추가해 같은 좌표의 선박 marker가 그 위에 보이게 한다.
      if (renderedPorts !== model.ports) {
        for (const marker of portMarkers) marker.remove()
        portMarkers = mergePortMarkers(model.ports).map((port) => {
          const element = portMarkerElement({
            ...port,
            // 선대 핀도 **장면이 있으면** 누를 수 있다 (`#1933`) — 종전에는 무조건 그림이라
            // 대시보드에서는 항만에 들어갈 길이 없었다.
            ...(port.appearance === 'fleet' && !port.enterable
              ? {}
              : { onActivate: () => emit({ type: 'selection', id: `port:${port.id}` }) }),
          })
          const projected = map.project?.([...port.coordinate])
          const placement = projected
            ? portLabelPlacement(projected.x, target.clientWidth)
            : 'center'
          element.dataset.placement = placement
        /*
         * 지구 뒤로 넘어가면 **완전히 감춘다** (`#1937`).
         *
         * MapLibre 기본값은 `0.2`라 반대편 마커가 희미하게 남는다. 3D 선체는 그때 아예
         * 그리지 않으므로(`vesselLayer.ts`), 배지만 떠 있으면 **배 없는 등급 표시**가 된다.
         */
          return new maplibregl.Marker({ element, anchor: 'center', opacityWhenCovered: '0' })
            .setLngLat([...port.coordinate]).addTo(map)
        })
        renderedPorts = model.ports
      }
      if (renderedMarkers !== model.markers) {
        for (const marker of markers) marker.remove()
        markers = model.markers.map(({ coordinate, element }) =>
          new maplibregl.Marker({ element, anchor: 'center', opacityWhenCovered: '0' })
            .setLngLat([...coordinate]).addTo(map),
        )
        renderedMarkers = model.markers
      }

      const source = map.getSource('routes') as maplibregl.GeoJSONSource | undefined
      if (source) source.setData(model.routes.data)
      else map.addSource('routes', {
        type: 'geojson', data: model.routes.data, attribution: model.routes.attribution,
      })
      if (map.getLayer?.('routes') === undefined) {
        const directStyle = routeStyle(model.mode === 'fleet' ? 'fleet-current' : 'comparison-direct')
        const detourStyle = routeStyle('comparison-detour')
        const accent = getComputedStyle(document.documentElement).getPropertyValue(directStyle.colorToken).trim()
        const detourColor = getComputedStyle(document.documentElement).getPropertyValue(detourStyle.colorToken).trim()
        const directPaint = {
          ...(accent === '' ? {} : { 'line-color': accent }),
          'line-width': directStyle.width, 'line-opacity': directStyle.opacity,
        }
        map.addLayer({
          id: 'routes', type: 'line', source: 'routes',
          filter: ['!=', ['get', 'kind'], 'DETOUR'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { ...directPaint, 'line-dasharray': [...directStyle.dash] },
        })
        map.addLayer({
          id: 'routes-detour', type: 'line', source: 'routes',
          filter: ['==', ['get', 'kind'], 'DETOUR'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            ...(detourColor === '' ? {} : { 'line-color': detourColor }),
            'line-width': detourStyle.width, 'line-opacity': detourStyle.opacity,
            'line-dasharray': [...detourStyle.dash],
          },
        })
      }
      if (model.mode === 'comparison' && map.getLayer?.('routes') !== undefined) {
        const direct = routeStyle('comparison-direct')
        const detour = routeStyle('comparison-detour')
        const pick = model.highlight ?? null
        const DIM = 0.22
        const css = getComputedStyle(document.documentElement)
        // 감속은 직항과 같은 길 — 고르면 그 선을 감속 색으로 바꾼다(`--route-slow`).
        const lineColor = css.getPropertyValue(pick === 'SLOW' ? '--route-slow' : direct.colorToken).trim()
        if (lineColor !== '') map.setPaintProperty('routes', 'line-color', lineColor)
        map.setPaintProperty('routes', 'line-opacity', pick === 'DETOUR' ? DIM : direct.opacity)
        map.setPaintProperty('routes', 'line-width', pick === 'DIRECT' || pick === 'SLOW' ? direct.width + 1.5 : direct.width)
        if (map.getLayer?.('routes-detour') !== undefined) {
          map.setPaintProperty('routes-detour', 'line-opacity', pick === 'DIRECT' || pick === 'SLOW' ? DIM : detour.opacity)
          map.setPaintProperty('routes-detour', 'line-width', pick === 'DETOUR' ? detour.width + 1.5 : detour.width)
        }
      }
      if (!fitted && !cameraPlaced && model.routes.bounds.length > 0) {
        const bounds = new maplibregl.LngLatBounds()
        for (const coordinate of unwrapDateline(model.routes.bounds)) bounds.extend([...coordinate])
        /*
         * 패딩을 **변마다** 준다 (#2051). 왼쪽만 오버레이가 가리는 만큼 더 밀고
         * 나머지 세 변은 종전 값 그대로다 — `maxZoom: 6`도 그대로 둔다(타일 자산이
         * z5까지라는 근거가 `basemap.ts`에 있다).
         */
        const gap = target.clientWidth <= 640 ? 24 : 48
        map.fitBounds(bounds, {
          padding: { top: gap, bottom: gap, right: gap, left: gap + overlayInsetStart(target) },
          maxZoom: 6,
          animate: false,
        })
        fitted = true
      }

      /*
       * 「이 배를 보여 달라」 (#1831) — **마커를 다 올린 뒤**다. 옮긴 뒤 알리는 쪽이
       * 듣고 바로 마커 자리를 재므로, 그 마커가 이미 지도에 있어야 한다.
       *
       * ⚠️ `animate: false`로 즉시 옮기고 **`moveend`에서** 알린다. 마커 DOM의 자리는
       * 지도가 움직임을 반영한 뒤라야 제 값이고, 그 전에 재면 카드가 옛 자리에 붙는다.
       */
      const focus = model.focus
      if (focus && focus.nonce !== focusedNonce) {
        focusedNonce = focus.nonce
        // 사용자가 고른 배로 옮겨 간 카메라다 — 늦게 온 항로가 그것을 다시 끌어가지 않는다.
        cameraPlaced = true
        map.once('moveend', () => {
          if (!destroyed) emit({ type: 'selection', id: focus.id })
        })
        map.easeTo({ center: [...focus.coordinate], animate: false })
      }
    }
    let vesselLayerPending = false
    /** 조건이 갖춰진 첫 순간에 3D 선체 layer를 올린다. 두 번 만들지 않는다. */
    const ensureVesselLayer = () => {
      if (!ready || vesselLayer !== null || vesselLayerPending) return
      // 3D 선체는 지구본 전용 layer다(`vesselLayer.ts`) — 평면에서는 클릭 마커(DOM)만 남는다.
      if (projection !== 'globe' || (model.vessels?.length ?? 0) === 0) return
      vesselLayerPending = true
      void import('./vesselLayer').then(({ createGlobeVesselLayer }) => {
        vesselLayerPending = false
        // 불러오는 사이 평면으로 바꿨으면 올리지 않는다 — 평면 위에 지구본용 선체가 뜬다(`#1976`).
        if (destroyed || projection !== 'globe') return
        vesselLayer = createGlobeVesselLayer(map, { mode: model.mode, vessels: model.vessels ?? [] })
      }, (error: unknown) => {
        vesselLayerPending = false
        emit({ type: 'error', error: error instanceof Error ? error : new Error(String(error)) })
      })
    }

    const toggle = quality.globe
      ? new ProjectionToggleControl(projection, (next) => switchProjection(next))
      : null
    if (toggle) map.addControl(toggle, 'top-right')

    /**
     * 투영을 바꾸고 **그에 딸린 것을 함께** 바꾼다 (`#1976`) — 기울기 · 회전 허용 · 3D 선체.
     * 투영만 바꾸면 평면인데 기울어진 채로 남거나, 평면 위에 지구본용 선체가 뜬다.
     */
    const applyProjection = (next: MapProjection, camera = true): boolean => {
      try {
        map.setProjection({ type: next })
      } catch (error) {
        // globe projection만 실패하면 MapLibre 기본 Mercator를 그대로 사용한다.
        console.warn('[MapLibreRenderer] globe를 사용할 수 없어 Mercator로 표시합니다.', error)
        return false
      }
      projection = next
      if (next === 'globe') {
        if (camera) {
          map.dragRotate.enable()
          map.touchZoomRotate.enableRotation()
          map.easeTo({ pitch: GLOBE_PITCH, animate: false })
        }
        ensureVesselLayer()
      } else {
        if (camera) {
          map.dragRotate.disable()
          map.touchZoomRotate.disableRotation()
          map.easeTo({ pitch: 0, bearing: 0, animate: false })
        }
        vesselLayer?.destroy()
        vesselLayer = null
      }
      return true
    }
    const switchProjection = (next: MapProjection) => {
      if (destroyed || next === projection) return
      if (ready && !applyProjection(next)) return
      // 지도가 뜨기 전이면 값만 바꾼다 — 아래 `load`가 그 값으로 적용한다.
      projection = next
      writeProjectionPreference(next)
      toggle?.setCurrent(next)
    }

    map.on('load', () => {
      // style이 준비된 뒤 projection을 바꿔야 MapLibre가 초기화 오류를 내지 않는다.
      // 정적 자산은 vector PMTiles뿐이라 DEM을 추정해 terrain을 만들지 않는다.
      // 전환할 수 있는 기기면 **지금 값으로 한 번 적용**한다 — 뜨기 전에 버튼을 눌렀다면
      // 생성자가 정한 기울기·회전이 그 값과 다를 수 있다. `low`는 평면 그대로다.
      if (quality.globe && !applyProjection(projection, (projection === 'globe') !== constructedGlobe)) {
        projection = 'mercator'
        toggle?.setCurrent(projection)
      }
      ready = true
      draw()
      ensureVesselLayer()
      emit({ type: 'ready' })
    })

    return {
      update(next) {
        model = next
        draw()
        // 선박이 **나중에 도착해도** 3D 선체가 선다 (`#1917`). 종전에는 `load` 시점에
        // 선박이 없으면 layer를 영영 만들지 않았다 — 목록을 서버에서 받는 화면에서는
        // 그 순간이 비어 있는 것이 정상이라, 배가 와도 평면 마커만 남았다.
        ensureVesselLayer()
        vesselLayer?.update({ mode: next.mode, vessels: next.vessels ?? [] })
      },
      destroy() {
        destroyed = true
        vesselLayer?.destroy()
        vesselLayer = null
        resizeObserver?.disconnect()
        for (const marker of markers) marker.remove()
        for (const marker of portMarkers) marker.remove()
        markers = []
        portMarkers = []
        map.remove()
      },
    }
  },
}
