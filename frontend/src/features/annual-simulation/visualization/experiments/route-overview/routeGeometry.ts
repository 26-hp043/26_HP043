export type RouteCoordinate = readonly [longitude: number, latitude: number]

type RouteGeometry = {
  position: RouteCoordinate
  bearing: number
  traveledCoordinates: RouteCoordinate[]
}

const EARTH_RADIUS_METERS = 6_371_008.8
const DEGREES_TO_RADIANS = Math.PI / 180
const RADIANS_TO_DEGREES = 180 / Math.PI
const MINIMUM_DISTANCE_METERS = 0.001

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

export function routeGeometryAtProgress(
  coordinates: readonly RouteCoordinate[],
  progress: number,
): RouteGeometry {
  if (!Number.isFinite(progress)) throw new RangeError('항로 진행률은 유한한 숫자여야 합니다.')

  const route = distinctCoordinates(coordinates)
  if (route.length < 2) throw new RangeError('항로에는 서로 다른 좌표가 두 개 이상 필요합니다.')

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
