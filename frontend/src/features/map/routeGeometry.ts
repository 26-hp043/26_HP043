export type RouteCoordinate = readonly [longitude: number, latitude: number]

interface RouteProgressGeometry {
  readonly position: RouteCoordinate
  readonly bearing: number
  readonly traveledCoordinates: readonly RouteCoordinate[]
}

type RouteSourceId = 'searoute/marnet'

/** 서버 응답의 자유 문구 대신 화면에서 사용하는 검증된 출처 메타데이터다. */
export interface RouteSource {
  readonly id: RouteSourceId
  readonly label: string
  readonly attribution: string
  readonly license: string
  readonly sourceUrl: string
  readonly displayOnly: true
}

/** 지도 화면들이 공유하는 표시용 항로 계약. 계산 거리의 근거로 사용하지 않는다. */
export interface RouteGeometry {
  readonly coordinates: readonly RouteCoordinate[]
  readonly source: RouteSource
  /** 없으면 기존 SeaRoute geometry다. WAYPOINT는 provider의 명시적 입력에만 붙는다. */
  readonly derivation?: WaypointRouteDerivation
}

export interface RouteWaypoint {
  readonly order: number
  readonly coordinate: RouteCoordinate
  readonly label?: string | null
}

export interface WaypointRouteDerivation {
  readonly kind: 'WAYPOINT'
  readonly waypoints: readonly RouteWaypoint[]
}

type RouteLineGeometry =
  | { readonly type: 'LineString'; readonly coordinates: readonly RouteCoordinate[] }
  | { readonly type: 'MultiLineString'; readonly coordinates: readonly (readonly RouteCoordinate[])[] }

const EARTH_RADIUS_METERS = 6_371_008.8
const DEGREES_TO_RADIANS = Math.PI / 180
const RADIANS_TO_DEGREES = 180 / Math.PI
const MINIMUM_DISTANCE_METERS = 0.001

const ROUTE_SOURCES: Readonly<Record<RouteSourceId, RouteSource>> = Object.freeze({
  'searoute/marnet': Object.freeze({
    id: 'searoute/marnet',
    label: 'Eurostat SeaRoute 해상 경로망',
    attribution: '해상 경로망 © Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)',
    license: 'Eurostat SeaRoute: EUPL-1.2; searoute: Apache-2.0',
    sourceUrl: 'https://github.com/eurostat/searoute',
    displayOnly: true,
  }),
})

/** 알려진 식별자만 정본 메타데이터로 바꾼다. 서버가 보낸 attribution은 사용하지 않는다. */
export function getKnownRouteSource(source: string): RouteSource | null {
  return Object.hasOwn(ROUTE_SOURCES, source)
    ? ROUTE_SOURCES[source as RouteSourceId]
    : null
}

function toRadians(value: number): number {
  return value * DEGREES_TO_RADIANS
}

function normalizeLongitude(value: number): number {
  return ((value + 540) % 360) - 180
}

function assertCoordinate(coordinate: RouteCoordinate): void {
  const [longitude, latitude] = coordinate
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude) ||
      longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    throw new RangeError('항로 좌표의 경도와 위도가 유효하지 않습니다.')
  }
}

function distanceBetween(from: RouteCoordinate, to: RouteCoordinate): number {
  const fromLatitude = toRadians(from[1])
  const toLatitude = toRadians(to[1])
  const latitudeDelta = toLatitude - fromLatitude
  const longitudeDelta = toRadians(to[0] - from[0])
  const haversine = Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(fromLatitude) * Math.cos(toLatitude) * Math.sin(longitudeDelta / 2) ** 2
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.min(1, Math.sqrt(haversine)))
}

function interpolateGreatCircle(
  from: RouteCoordinate,
  to: RouteCoordinate,
  fraction: number,
): RouteCoordinate {
  if (fraction <= 0) return from
  if (fraction >= 1) return to

  const angularDistance = distanceBetween(from, to) / EARTH_RADIUS_METERS
  const sineAngularDistance = Math.sin(angularDistance)
  if (Math.abs(sineAngularDistance) < Number.EPSILON) return from

  const fromLatitude = toRadians(from[1])
  const fromLongitude = toRadians(from[0])
  const toLatitude = toRadians(to[1])
  const toLongitude = toRadians(to[0])
  const fromWeight = Math.sin((1 - fraction) * angularDistance) / sineAngularDistance
  const toWeight = Math.sin(fraction * angularDistance) / sineAngularDistance
  const x = fromWeight * Math.cos(fromLatitude) * Math.cos(fromLongitude) +
    toWeight * Math.cos(toLatitude) * Math.cos(toLongitude)
  const y = fromWeight * Math.cos(fromLatitude) * Math.sin(fromLongitude) +
    toWeight * Math.cos(toLatitude) * Math.sin(toLongitude)
  const z = fromWeight * Math.sin(fromLatitude) + toWeight * Math.sin(toLatitude)

  return [
    normalizeLongitude(Math.atan2(y, x) * RADIANS_TO_DEGREES),
    Math.atan2(z, Math.sqrt(x ** 2 + y ** 2)) * RADIANS_TO_DEGREES,
  ]
}

function bearingBetween(from: RouteCoordinate, to: RouteCoordinate): number {
  const fromLatitude = toRadians(from[1])
  const toLatitude = toRadians(to[1])
  const longitudeDelta = toRadians(to[0] - from[0])
  const y = Math.sin(longitudeDelta) * Math.cos(toLatitude)
  const x = Math.cos(fromLatitude) * Math.sin(toLatitude) -
    Math.sin(fromLatitude) * Math.cos(toLatitude) * Math.cos(longitudeDelta)
  return (Math.atan2(y, x) * RADIANS_TO_DEGREES + 360) % 360
}

function distinctCoordinates(coordinates: readonly RouteCoordinate[]): RouteCoordinate[] {
  const result: RouteCoordinate[] = []
  for (const coordinate of coordinates) {
    assertCoordinate(coordinate)
    const previous = result.at(-1)
    if (!previous || distanceBetween(previous, coordinate) > MINIMUM_DISTANCE_METERS) {
      result.push(coordinate)
    }
  }
  return result
}

function validatedRoute(coordinates: readonly RouteCoordinate[]): RouteCoordinate[] {
  const route = distinctCoordinates(coordinates)
  if (route.length < 2) throw new RangeError('항로에는 서로 다른 좌표가 두 개 이상 필요합니다.')
  return route
}

/** 좌표점의 간격과 무관하게 누적 대권거리 기준 진행 위치를 계산한다. */
export function routeGeometryAtProgress(
  coordinates: readonly RouteCoordinate[],
  progress: number,
): RouteProgressGeometry {
  if (!Number.isFinite(progress)) throw new RangeError('항로 진행률은 유한한 숫자여야 합니다.')

  const route = validatedRoute(coordinates)
  const segmentLengths = route.slice(1).map((coordinate, index) =>
    distanceBetween(route[index], coordinate),
  )
  const totalDistance = segmentLengths.reduce((sum, distance) => sum + distance, 0)
  const targetDistance = totalDistance * Math.min(1, Math.max(0, progress))
  let distanceBeforeSegment = 0
  let segmentIndex = segmentLengths.length - 1

  for (let index = 0; index < segmentLengths.length; index += 1) {
    if (targetDistance <= distanceBeforeSegment + segmentLengths[index]) {
      segmentIndex = index
      break
    }
    distanceBeforeSegment += segmentLengths[index]
  }

  const segmentFraction = (targetDistance - distanceBeforeSegment) / segmentLengths[segmentIndex]
  const position = interpolateGreatCircle(route[segmentIndex], route[segmentIndex + 1], segmentFraction)
  const traveledCoordinates = route.slice(0, segmentIndex + 1)
  if (distanceBetween(traveledCoordinates.at(-1)!, position) > MINIMUM_DISTANCE_METERS) {
    traveledCoordinates.push(position)
  }

  return {
    position,
    bearing: bearingBetween(route[segmentIndex], route[segmentIndex + 1]),
    traveledCoordinates,
  }
}

/** 좌표와 검증된 출처를 하나의 표시용 항로 계약으로 만든다. */
export function createRouteGeometry(
  coordinates: readonly RouteCoordinate[],
  source: RouteSource,
): RouteGeometry {
  return { coordinates: validatedRoute(coordinates), source }
}

/** provider가 순서와 좌표를 함께 명시한 계획 waypoint만 geometry로 만든다. */
export function createWaypointRouteGeometry(
  waypoints: readonly RouteWaypoint[],
  source: RouteSource,
): RouteGeometry {
  if (!source) throw new Error('Waypoint 항로에는 검증된 출처가 필요합니다.')
  if (waypoints.length < 2) throw new RangeError('Waypoint 항로에는 두 개 이상의 지점이 필요합니다.')
  const seen = new Set<string>()
  let previousOrder = -1
  for (const waypoint of waypoints) {
    if (!Number.isInteger(waypoint.order) || waypoint.order < 0 || waypoint.order <= previousOrder) {
      throw new RangeError('Waypoint 순서는 중복 없이 오름차순이어야 합니다.')
    }
    assertCoordinate(waypoint.coordinate)
    const key = `${waypoint.coordinate[0]}:${waypoint.coordinate[1]}`
    if (seen.has(key)) throw new RangeError('Waypoint 좌표는 중복될 수 없습니다.')
    seen.add(key)
    previousOrder = waypoint.order
  }
  const preserved = waypoints.map((waypoint) => ({
    order: waypoint.order,
    coordinate: [...waypoint.coordinate] as RouteCoordinate,
    ...(waypoint.label === undefined ? {} : { label: waypoint.label }),
  }))
  return {
    coordinates: validatedRoute(preserved.map(({ coordinate }) => coordinate)),
    source,
    derivation: { kind: 'WAYPOINT', waypoints: preserved },
  }
}

/** 날짜변경선을 지나는 선을 양쪽 경계에서 끊어 GeoJSON이 세계를 가로지르지 않게 한다. */
export function routeLineGeometry(coordinates: readonly RouteCoordinate[]): RouteLineGeometry {
  const route = validatedRoute(coordinates)
  const lines: RouteCoordinate[][] = [[route[0]]]

  for (let index = 1; index < route.length; index += 1) {
    const from = route[index - 1]
    const to = route[index]
    const rawDelta = to[0] - from[0]
    if (Math.abs(rawDelta) <= 180) {
      lines.at(-1)!.push(to)
      continue
    }

    const longitudeDelta = rawDelta > 180 ? rawDelta - 360 : rawDelta + 360
    const boundary = longitudeDelta > 0 ? 180 : -180
    const oppositeBoundary = boundary === 180 ? -180 : 180
    const fraction = (boundary - from[0]) / longitudeDelta
    const latitude = from[1] + (to[1] - from[1]) * fraction
    lines.at(-1)!.push([boundary, latitude])
    lines.push([[oppositeBoundary, latitude], to])
  }

  return lines.length === 1
    ? { type: 'LineString', coordinates: lines[0] }
    : { type: 'MultiLineString', coordinates: lines }
}
