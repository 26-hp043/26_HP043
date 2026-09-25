import type { MapVessel } from '../fleet/types'
import type { RouteLine, SeaRouteRequest } from '../fleet/seaRoute'
import type { MapGeometry, SnapshotRouteGeometry } from '../annual-simulation/visualization/model'
import type { SamplePort } from '../ports/samplePorts'
import type { PortMarkerModel } from './portMarkers'
import { createRouteGeometry, createWaypointRouteGeometry, getKnownRouteSource } from './routeGeometry'
import type { WaypointRouteDerivation } from './routeGeometry'

interface AdaptedPosition {
  readonly vessel: MapVessel
  readonly lat: number
  readonly lon: number
}

export interface AdaptedRouteRequest {
  readonly name: string
  readonly kind: 'DIRECT' | 'DETOUR'
  readonly request: SeaRouteRequest
}

interface FleetMapAdapterModel {
  readonly positions: readonly AdaptedPosition[]
  readonly routes: readonly AdaptedRouteRequest[]
  readonly ports: readonly PortMarkerModel[]
}

interface RouteMapAdapterModel {
  readonly routes: readonly AdaptedRouteRequest[]
  readonly ports: readonly PortMarkerModel[]
}

function finiteCoordinate(value: unknown, limit: number): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(number) && Math.abs(number) <= limit ? number : null
}

function isWaypointDerivation(value: unknown): value is WaypointRouteDerivation {
  return typeof value === 'object' && value !== null &&
    'kind' in value && value.kind === 'WAYPOINT' &&
    'waypoints' in value && Array.isArray(value.waypoints)
}

/** Fleet API의 정상·legacy 문자열·null·invalid 좌표를 renderer 입력 전에 판정한다. */
export function adaptFleetMap(
  vessels: readonly MapVessel[],
  extra: readonly RouteLine[],
  samplePorts: readonly SamplePort[] = [],
): FleetMapAdapterModel {
  const positions = vessels.flatMap((vessel): AdaptedPosition[] => {
    const lat = finiteCoordinate(vessel.lat, 90)
    const lon = finiteCoordinate(vessel.lon, 180)
    return lat === null || lon === null ? [] : [{ vessel, lat, lon }]
  })
  const vesselRoutes = positions.flatMap(({ vessel }): AdaptedRouteRequest[] => {
    if (!vessel.route) return []
    const fromLat = finiteCoordinate(vessel.route.departureLat, 90)
    const fromLon = finiteCoordinate(vessel.route.departureLon, 180)
    const toLat = finiteCoordinate(vessel.route.arrivalLat, 90)
    const toLon = finiteCoordinate(vessel.route.arrivalLon, 180)
    if (fromLat === null || fromLon === null || toLat === null || toLon === null) return []
    return [{ name: vessel.name, kind: 'DIRECT', request: { fromLat, fromLon, toLat, toLon } }]
  })
  const explicit = adaptRouteMap(extra, samplePorts)
  const routes = vesselRoutes.concat(explicit.routes)
  const vesselPorts = fleetPorts(positions, samplePorts)
  return { positions, routes, ports: vesselPorts.concat(explicit.ports) }
}

/** 선대 지도는 진행 중 항차의 두 끝만 무채색 핀으로 표시한다 (#1882). */
function fleetPorts(positions: readonly AdaptedPosition[], samplePorts: readonly SamplePort[]): readonly PortMarkerModel[] {
  const pins = new Map<string, PortMarkerModel>()
  for (const { vessel } of positions) {
    const route = vessel.route
    if (!route) continue
    const ends = [
      { lat: route.departureLat, lon: route.departureLon, name: route.departurePortName, role: 'departure' as const },
      { lat: route.arrivalLat, lon: route.arrivalLon, name: route.arrivalPortName, role: 'destination' as const },
    ]
    for (const end of ends) {
      const lat = finiteCoordinate(end.lat, 90)
      const lon = finiteCoordinate(end.lon, 180)
      if (lat === null || lon === null) continue
      const key = `${lat.toFixed(4)},${lon.toFixed(4)}`
      const label = end.name ?? samplePorts.find((port) => port.lat === lat && port.lon === lon)?.name_ko ?? ''
      const previous = pins.get(key)
      if (!previous || (!previous.label && label)) pins.set(key, {
        id: `fleet:${key}`, role: end.role, label, coordinate: [lon, lat], appearance: 'fleet',
      })
    }
  }
  return [...pins.values()]
}

/** 선박과 무관한 Comparison 입력을 renderer의 route·port model로 바꾼다. */
export function adaptRouteMap(
  routes: readonly RouteLine[],
  samplePorts: readonly SamplePort[] = [],
): RouteMapAdapterModel {
  const adapted = routes.flatMap((route): AdaptedRouteRequest[] => {
    const fromLat = finiteCoordinate(route.departureLat, 90)
    const fromLon = finiteCoordinate(route.departureLon, 180)
    const toLat = finiteCoordinate(route.arrivalLat, 90)
    const toLon = finiteCoordinate(route.arrivalLon, 180)
    if (fromLat === null || fromLon === null || toLat === null || toLon === null) return []
    return [{
      name: route.name, kind: route.kind ?? 'DIRECT',
      request: { fromLat, fromLon, toLat, toLon, via: route.via ?? null },
    }]
  })
  return { routes: adapted, ports: routePorts(adapted, samplePorts, true) }
}

function routePorts(
  routes: readonly AdaptedRouteRequest[],
  samplePorts: readonly SamplePort[],
  useRouteNames: boolean,
): readonly PortMarkerModel[] {
  const portAt = (lon: number, lat: number) => samplePorts.find((port) => port.lon === lon && port.lat === lat)
  const ports = routes.flatMap(({ request, name, kind }): PortMarkerModel[] => {
    const found: PortMarkerModel[] = []
    const departure = portAt(request.fromLon, request.fromLat)
    const destination = portAt(request.toLon, request.toLat)
    const waypoint = request.via ? portAt(request.via.lon, request.via.lat) : undefined
    found.push({
      id: `departure:${departure?.locode ?? `${request.fromLon}:${request.fromLat}`}`,
      role: 'departure', label: departure?.name_ko ?? '출발지', coordinate: [request.fromLon, request.fromLat],
    })
    found.push({
      id: `destination:${destination?.locode ?? `${request.toLon}:${request.toLat}`}`,
      role: 'destination', label: destination?.name_ko ?? (useRouteNames && kind === 'DIRECT' ? name : '도착지'), coordinate: [request.toLon, request.toLat],
    })
    if (request.via) found.push({
      id: `waypoint:${waypoint?.locode ?? `${request.via.lon}:${request.via.lat}`}`,
      role: 'waypoint', label: waypoint?.name_ko ?? (useRouteNames ? name.replace(/^우회 · /, '') : '경유지'), coordinate: [request.via.lon, request.via.lat],
    })
    return found
  })
  return ports
}

interface ComparisonMapInput {
  readonly currentLat: string
  readonly currentLon: string
  readonly destinationLat: string
  readonly destinationLon: string
  readonly destinationName: string
  readonly detourWaypointLat: string
  readonly detourWaypointLon: string
  readonly detourWaypointName: string
}

/** Comparison 폼의 null/반쪽/invalid 좌표에서는 항로를 추정하지 않는다. */
export function adaptComparisonRoutes(input: ComparisonMapInput): readonly RouteLine[] {
  const departureLat = finiteCoordinate(input.currentLat, 90)
  const departureLon = finiteCoordinate(input.currentLon, 180)
  const arrivalLat = finiteCoordinate(input.destinationLat, 90)
  const arrivalLon = finiteCoordinate(input.destinationLon, 180)
  if (departureLat === null || departureLon === null || arrivalLat === null || arrivalLon === null) return []
  const ends = { departureLat, departureLon, arrivalLat, arrivalLon }
  const direct: RouteLine = { ...ends, name: input.destinationName || '목적항', kind: 'DIRECT' }
  const viaLat = finiteCoordinate(input.detourWaypointLat, 90)
  const viaLon = finiteCoordinate(input.detourWaypointLon, 180)
  if (viaLat === null || viaLon === null) return [direct]
  return [direct, {
    ...ends, name: `우회 · ${input.detourWaypointName || '경유지'}`, kind: 'DETOUR',
    via: { lat: viaLat, lon: viaLon },
  }]
}

/** Annual 좌표는 같은 snapshot과 allowlist source를 모두 확인한 뒤에만 통과한다. */
export function adaptAnnualMapGeometry(snapshotId: string, geometry: MapGeometry): MapGeometry {
  if (geometry.status === 'unavailable') return geometry
  if (geometry.snapshotId !== snapshotId) throw new Error('지도 좌표의 스냅샷이 시뮬레이션 결과와 다릅니다.')
  const routes = geometry.routes.map((route) => {
    const source = getKnownRouteSource(route.source?.id ?? '')
    if (!source) throw new Error('지도 항로의 출처가 없거나 허용되지 않았습니다.')
    try {
      const derivation: unknown = route.derivation
      if (derivation !== undefined && !isWaypointDerivation(derivation)) {
        throw new Error('지도 항로의 derivation이 허용되지 않았습니다.')
      }
      const geometry = derivation
        ? createWaypointRouteGeometry(derivation.waypoints, source)
        : createRouteGeometry(route.coordinates, source)
      return {
        ...geometry,
        snapshotVoyageId: route.snapshotVoyageId,
        ...(route.playbackDurationMs === undefined ? {} : { playbackDurationMs: route.playbackDurationMs }),
        ...(route.startedAt === undefined ? {} : { startedAt: route.startedAt }),
        ...(route.endedAt === undefined ? {} : { endedAt: route.endedAt }),
        ...(route.vesselName === undefined ? {} : { vesselName: route.vesselName }),
        ...(route.departureName === undefined ? {} : { departureName: route.departureName }),
        ...(route.arrivalName === undefined ? {} : { arrivalName: route.arrivalName }),
        ...(route.speedKnots === undefined ? {} : { speedKnots: route.speedKnots }),
        ...(route.emission === undefined ? {} : { emission: route.emission }),
      } satisfies SnapshotRouteGeometry
    } catch {
      throw new Error('지도 항로 좌표가 없거나 유효하지 않습니다.')
    }
  })
  return { ...geometry, routes }
}
