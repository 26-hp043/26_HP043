import type { MapVessel } from '../fleet/types'
import { harborSceneFor } from './harborScenes'
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

/**
 * 정박한 배를 **그 자리의 항만**에 잇는 거리(도).
 *
 * 약 0.25° — 위도에 따라 22~28 km다. 묘박지는 부두에서 수 km 떨어지므로 좁게 잡으면
 * 정박 중인 배 옆에 항만이 뜨지 않는다.
 *
 * ⚠️ **접안을 주장하지 않는다.** 이 핀이 말하는 것은 「여기 이 항만이 있다」이고, 배가
 * 그 항에 접안했다는 판정이 아니다 — 서버가 주는 것은 `underwayState`(정박 여부)뿐이고
 * 어느 부두인지는 이 제품에 없다(`MAP_VISUALIZATION_GUIDE`).
 */
const BERTH_NEAR_DEGREES = 0.25

/** 그 좌표에서 가장 가까운 샘플 항만. 위 거리 밖이면 `null`이다. */
function portNear(
  lat: number,
  lon: number,
  samplePorts: readonly SamplePort[],
): SamplePort | null {
  let best: SamplePort | null = null
  let bestDistance = BERTH_NEAR_DEGREES
  for (const port of samplePorts) {
    // 경도는 위도가 높을수록 촘촘해진다 — 그만큼 보정해야 북쪽 항이 억울하게 멀어지지 않는다.
    const dLat = port.lat - lat
    const dLon = (port.lon - lon) * Math.cos((lat * Math.PI) / 180)
    const distance = Math.sqrt(dLat * dLat + dLon * dLon)
    if (distance <= bestDistance) {
      best = port
      bestDistance = distance
    }
  }
  return best
}

/**
 * 선대 지도의 항구 핀 (#1882 · `#1933`).
 *
 * 둘을 세운다.
 *
 * ⑴ **진행 중 항차의 두 끝** — 어디서 떠나 어디로 가는가(`#1882`)
 * ⑵ **정박 중인 배 옆의 항만** (`#1933`) — 종전에는 항차가 없으면 핀이 하나도 서지
 *    않아, 배 셋이 정박해 있어도 지도에 항만이 없었다. 정박은 **항만에서 일어나는 일**이라
 *    그 자리를 비워 두면 「이 배가 어디 있나」의 답이 반쪽이 된다.
 *
 * 장면이 있는 항만(`harborScenes.ts`)은 **누를 수 있는 핀**이 된다 — 눌러 항만으로 들어간다.
 */
function fleetPorts(positions: readonly AdaptedPosition[], samplePorts: readonly SamplePort[]): readonly PortMarkerModel[] {
  const pins = new Map<string, PortMarkerModel>()

  const remember = (
    lat: number,
    lon: number,
    role: PortMarkerModel['role'],
    label: string,
    locode: string | null,
  ) => {
    const key = `${lat.toFixed(4)},${lon.toFixed(4)}`
    const id = locode === null ? `fleet:${key}` : `fleet:${locode}:${key}`
    const previous = pins.get(key)
    if (previous && previous.label && !label) return
    pins.set(key, {
      id, role, label, coordinate: [lon, lat], appearance: 'fleet',
      enterable: harborSceneFor(id) !== null,
    })
  }

  // ⑵ 정박 중인 배 옆의 항만. 먼저 넣어 두고, 항차 끝이 같은 자리면 그쪽 역할이 이긴다.
  for (const { vessel, lat, lon } of positions) {
    if (vessel.underwayState !== 'NOT_UNDER_WAY') continue
    const port = portNear(lat, lon, samplePorts)
    if (!port) continue
    remember(port.lat, port.lon, 'berth', port.name_ko || port.name, port.locode)
  }

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
      /*
       * 어느 항인지 세 단계로 찾는다 (`#1933`).
       *
       * 좌표가 **정확히** 같은 항 → 이름이 같은 항 → 그 자리에서 가장 가까운 항.
       * 종전에는 첫 단계뿐이었다. 항차 좌표가 항만표와 소수점 한 자리만 달라도 LOCODE를
       * 찾지 못했고, 그래서 **싱가포르처럼 장면이 있는 항이 그림으로 남았다** — 들어갈
       * 곳이 있는데 문이 없는 상태다.
       *
       * ⚠️ 찾은 것은 **어느 항만인지**일 뿐, 접안 사실이 아니다. 이름을 지어내지도 않는다 —
       * 라벨은 서버가 준 이름을 그대로 쓰고, 못 찾으면 LOCODE 없이 그림으로 남는다.
       */
      const named = end.name?.trim().toUpperCase()
      const found = samplePorts.find((port) => port.lat === lat && port.lon === lon)
        ?? (named ? samplePorts.find((port) => port.name.toUpperCase() === named || port.name_ko === end.name) : undefined)
        ?? portNear(lat, lon, samplePorts)
      remember(lat, lon, end.role, end.name ?? found?.name_ko ?? '', found?.locode ?? null)
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
