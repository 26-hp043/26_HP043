import * as maplibregl from 'maplibre-gl'
import { ensureMapLibreWorker } from './mapLibreWorker'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from '../fleet/basemap'
import { fetchSeaRoute, type SeaRouteRequest } from '../fleet/seaRoute'
import { routeLineGeometry, type RouteCoordinate } from './routeGeometry'
import type { MapModeInput, MapRenderer } from './renderer'
import { routeStyle } from './routeStyles'
import {
  createSimulationPlaybackController,
  type SimulationPlaybackController,
  type SimulationPlaybackState,
} from '../annual-simulation/visualization/playbackController'
import {
  createFollowCameraController,
  type FollowCameraController,
  type PlaybackCameraMode,
} from '../annual-simulation/visualization/followCamera'
import { mapQualityPolicy, type MapQualityTier } from './quality'
import type { GlobeVesselLayerController } from './vesselLayer'
import { vesselWake } from './vesselModel'

type PlaybackRoute =
  | { readonly source: 'sea-route'; readonly request: SeaRouteRequest }
  | {
      readonly source: 'provided-coordinates'
      readonly coordinates: readonly RouteCoordinate[]
      readonly routeLines?: readonly (readonly RouteCoordinate[])[]
    }

interface PlaybackRendererModel extends Extract<MapModeInput, { readonly mode: 'playback' }> {
  readonly route: PlaybackRoute
  readonly bearing: number
  readonly pitch: number
  readonly controller?: SimulationPlaybackController
  readonly cameraMode?: PlaybackCameraMode
  readonly resetViewToken?: number
  readonly reducedMotion?: boolean
  readonly qualityTier?: MapQualityTier
  readonly speedKnots?: number | null
}

function failure(code: string, message: string): Error {
  const error = new Error(message)
  error.name = code
  return error
}

/** Annual의 명시적 geometry를 재생하는 공용 MapLibre adapter다. */
export const playbackRenderer: MapRenderer<PlaybackRendererModel> = {
  mount(target, initialModel, emit) {
    let model = initialModel
    let disposed = false
    let controller: SimulationPlaybackController | null = null
    let ownsController = false
    let playbackCleanup: (() => void) | null = null
    let camera: FollowCameraController | null = null
    let marker: maplibregl.Marker | null = null
    let map: maplibregl.Map | null = null
    let vesselLayer: GlobeVesselLayerController | null = null

    const start = async () => {
      try {
        const quality = mapQualityPolicy({ override: model.qualityTier })
        if (!await hasBasemap()) throw failure('asset-missing', 'PMTiles 지도 자산을 찾을 수 없습니다.')
        if (disposed) return
        const probe = document.createElement('canvas')
        if (!probe.getContext('webgl2') && !probe.getContext('webgl')) throw failure('webgl-unavailable', 'WebGL을 사용할 수 없습니다.')
        // 워커 주소를 지도보다 먼저 정한다 (`#1909`).
        ensureMapLibreWorker()
        const registry = globalThis as { __bluelogPmtiles?: Protocol }
        if (!registry.__bluelogPmtiles) {
          const protocol = new Protocol()
          maplibregl.addProtocol('pmtiles', protocol.tile)
          registry.__bluelogPmtiles = protocol
        }
        const instance = new maplibregl.Map({
          container: target,
          style: {
            version: 8, glyphs: `${BASEMAP_FONTS_URL}/{fontstack}/{range}.pbf`,
            sources: {
              protomaps: { type: 'vector', url: `pmtiles://${BASEMAP_URL}`, attribution: '© OpenStreetMap' },
              playbackRoute: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
              playbackTraveled: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
            },
            layers: layers('protomaps', namedFlavor('light'), { lang: 'ko' }),
          },
          center: [125, 22], zoom: 3, maxZoom: MAX_ZOOM, pitch: quality.globe ? model.pitch : 0, bearing: model.bearing,
          maxPitch: quality.globe ? 55 : 0, dragRotate: quality.globe, pitchWithRotate: quality.globe, touchZoomRotate: quality.globe,
          attributionControl: { compact: true },
        })
        map = instance
        instance.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
        instance.on('rotate', () => emit({ type: 'selection', id: `bearing:${Math.round(instance.getBearing())}` }))
        instance.on('pitch', () => emit({ type: 'selection', id: `pitch:${Math.round(instance.getPitch())}` }))
        let coordinates: readonly RouteCoordinate[]
        try {
          coordinates = model.route.source === 'sea-route' ? (await fetchSeaRoute(model.route.request)).coordinates : model.route.coordinates
        } catch (error) {
          throw failure('route-failed', error instanceof Error ? error.message : String(error))
        }
        if (disposed) return
        const geometry = model.route.source === 'provided-coordinates' && model.route.routeLines
          ? { type: 'MultiLineString' as const, coordinates: model.route.routeLines.map((line) => line.map((coordinate) => [...coordinate])) }
          : routeLineGeometry(coordinates)
        await new Promise<void>((resolve, reject) => {
          if (instance.loaded()) resolve()
          else {
            instance.once('load', () => resolve())
            instance.once('error', (event) => reject(event.error))
          }
        })
        if (disposed) return
        ;(instance.getSource('playbackRoute') as maplibregl.GeoJSONSource).setData({ type: 'Feature', properties: {}, geometry })
        const remainingStyle = routeStyle('playback-remaining')
        const traveledStyle = routeStyle('playback-traveled')
        const color = getComputedStyle(document.documentElement).getPropertyValue(remainingStyle.colorToken).trim()
        instance.addLayer({
          id: 'playbackRoute', type: 'line', source: 'playbackRoute',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            ...(color === '' ? {} : { 'line-color': color }),
            'line-width': remainingStyle.width, 'line-opacity': remainingStyle.opacity,
            'line-dasharray': [...remainingStyle.dash],
          },
        })
        instance.addLayer({
          id: 'playbackTraveled', type: 'line', source: 'playbackTraveled',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            ...(color === '' ? {} : { 'line-color': color }),
            'line-width': traveledStyle.width, 'line-opacity': traveledStyle.opacity,
            'line-dasharray': [...traveledStyle.dash],
          },
        })
        const bounds = new maplibregl.LngLatBounds()
        const boundsCoordinates = model.route.source === 'provided-coordinates' && model.route.routeLines
          ? model.route.routeLines.flat()
          : coordinates
        for (const coordinate of boundsCoordinates) bounds.extend([...coordinate])
        const showOverview = () => instance.fitBounds(bounds, { padding: 90, maxZoom: 4.5, pitch: model.pitch, bearing: model.bearing, animate: false })
        showOverview()
        const ship = document.createElement('span')
        ship.textContent = '◆'
        ship.style.cssText = 'font-size:24px;color:#063a66;text-shadow:0 0 3px white'
        ship.setAttribute('role', 'img')
        ship.setAttribute('aria-label', '재생 항로의 이동 선박')
        marker = new maplibregl.Marker({ element: ship, anchor: 'center' }).setLngLat([...coordinates[0]]).addTo(instance)
        if (quality.globe) {
          try {
            const { createGlobeVesselLayer } = await import('./vesselLayer')
            if (disposed) return
            vesselLayer = createGlobeVesselLayer({
              mode: 'playback', vessels: [{ id: 'playback-vessel', coordinate: coordinates[0], heading: null }],
            })
            instance.addLayer(vesselLayer.layer)
          } catch (error) {
            // 3D 선박만 실패하면 DOM marker와 playback은 유지한다.
            console.warn('[PlaybackRenderer] 3D 선박 layer를 사용할 수 없습니다.', error)
          }
        }
        const interactions = new Set<() => void>()
        const userInteraction = () => interactions.forEach((listener) => listener())
        instance.on('dragstart', userInteraction)
        instance.on('rotatestart', userInteraction)
        camera = createFollowCameraController({
          follow(position, nextBearing, animate) {
            instance.easeTo({ center: [...position], ...(nextBearing === null ? {} : { bearing: nextBearing }), duration: animate ? 300 : 0 })
          },
          showOverview,
          subscribeUserInteraction(listener) { interactions.add(listener); return () => interactions.delete(listener) },
        }, {
          reducedMotion: !quality.animate || model.reducedMotion === true,
          onModeChange: (mode) => emit({ type: 'selection', id: `camera:${mode}` }),
        })
        camera.setMode(model.cameraMode ?? 'overview')
        controller = model.controller ?? createSimulationPlaybackController({ coordinates, durationMs: 18_000 })
        ownsController = model.controller === undefined
        playbackCleanup = controller.subscribe((playback: SimulationPlaybackState) => {
          if (disposed || !marker || playback.status === 'unavailable') return
          marker.setLngLat([...playback.position])
          vesselLayer?.update({
            mode: 'playback',
            vessels: [{
              id: 'playback-vessel', coordinate: playback.position,
              heading: playback.activeRouteBearing,
              wake: vesselWake(model.speedKnots, playback.motion === 'playing', quality.animate && model.reducedMotion !== true),
            }],
          })
          camera?.update(playback.position, playback.traveledCoordinates)
          if (playback.traveledCoordinates.length >= 2) {
            const traveledSource = instance.getSource('playbackTraveled') as maplibregl.GeoJSONSource
            traveledSource.setData({
              type: 'Feature', properties: {},
              geometry: { type: 'LineString', coordinates: playback.traveledCoordinates.map((coordinate) => [...coordinate]) },
            })
          }
        })
        if (ownsController) controller.restart()
        emit({ type: 'ready' })
      } catch (error) {
        if (!disposed) emit({ type: 'error', error: error instanceof Error ? error : failure('map-failed', String(error)) })
      }
    }
    void start()
    return {
      update(next) {
        const reset = next.resetViewToken !== model.resetViewToken
        model = next
        camera?.setReducedMotion(next.reducedMotion ?? false)
        if (next.reducedMotion) controller?.pause()
        map?.rotateTo(next.bearing)
        map?.setPitch(next.pitch)
        camera?.setMode(next.cameraMode ?? 'overview')
        if (reset) camera?.resetView()
      },
      destroy() {
        disposed = true
        playbackCleanup?.()
        camera?.destroy()
        if (ownsController) controller?.destroy()
        marker?.remove()
        map?.remove()
      },
    }
  },
}
