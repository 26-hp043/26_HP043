import { describe, expect, it } from 'vitest'
import {
  createWaypointRouteGeometry,
  getKnownRouteSource,
  routeGeometryAtProgress,
  routeLineGeometry,
  type RouteCoordinate,
} from './routeGeometry'

describe('공용 항로 geometry', () => {
  const unevenRoute: RouteCoordinate[] = [[0, 0], [1, 0], [10, 0]]

  it('진행률 0·0.5·1에서 시작·중간·끝과 지나온 좌표를 반환한다', () => {
    const start = routeGeometryAtProgress([[0, 0], [10, 0]], 0)
    const middle = routeGeometryAtProgress([[0, 0], [10, 0]], 0.5)
    const end = routeGeometryAtProgress([[0, 0], [10, 0]], 1)

    expect(start.position).toEqual([0, 0])
    expect(start.traveledCoordinates).toEqual([[0, 0]])
    expect(middle.position).toEqual([5, 0])
    expect(middle.traveledCoordinates).toEqual([[0, 0], [5, 0]])
    expect(end.position).toEqual([10, 0])
    expect(end.traveledCoordinates).toEqual([[0, 0], [10, 0]])
    expect([start.bearing, middle.bearing, end.bearing]).toEqual([90, 90, 90])
  })

  it('유효하지 않은 좌표와 진행률을 거부한다', () => {
    expect(() => routeLineGeometry([[181, 0], [0, 0]])).toThrow('항로 좌표')
    expect(() => routeLineGeometry([[0, Number.NaN], [1, 0]])).toThrow('항로 좌표')
    expect(() => routeGeometryAtProgress(unevenRoute, Number.POSITIVE_INFINITY)).toThrow('항로 진행률')
  })

  it('연속 중복을 제거하고 서로 다른 좌표가 부족하면 거부한다', () => {
    expect(routeLineGeometry([[0, 0], [0, 0], [2, 0]])).toEqual({
      type: 'LineString',
      coordinates: [[0, 0], [2, 0]],
    })
    expect(() => routeLineGeometry([[129, 35], [129, 35]])).toThrow('서로 다른 좌표')
  })

  it('불균등한 좌표 간격에서도 누적 대권거리 기준으로 이동한다', () => {
    expect(routeGeometryAtProgress(unevenRoute, 0.25).position).toEqual([2.5, 0])
    expect(routeGeometryAtProgress(unevenRoute, 0.5).position).toEqual([5, 0])
    expect(routeGeometryAtProgress(unevenRoute, 0.75).position).toEqual([7.5, 0])
  })

  it('좌표 밀도가 달라도 같은 진행률 증분은 같은 거리 증분이다', () => {
    const sparse: RouteCoordinate[] = [[0, 0], [12, 0]]
    const dense: RouteCoordinate[] = [[0, 0], [1, 0], [2, 0], [3, 0], [12, 0]]
    const progresses = [0, 0.25, 0.5, 0.75, 1]

    expect(progresses.map((progress) => routeGeometryAtProgress(sparse, progress).position[0]))
      .toEqual([0, 3, 6, 9, 12])
    expect(progresses.map((progress) => routeGeometryAtProgress(dense, progress).position[0]))
      .toEqual([0, 3, 6, 9, 12])
  })

  it('진행률을 범위 안으로 제한하고 지나온 항로를 반환한다', () => {
    expect(routeGeometryAtProgress(unevenRoute, -1).traveledCoordinates).toEqual([[0, 0]])
    expect(routeGeometryAtProgress(unevenRoute, 0.5).traveledCoordinates)
      .toEqual([[0, 0], [1, 0], [5, 0]])
    expect(routeGeometryAtProgress(unevenRoute, 2).position).toEqual([10, 0])
  })

  it('동·서·남·북 방향의 방위를 계산한다', () => {
    expect(routeGeometryAtProgress([[0, 0], [1, 0]], 0.5).bearing).toBeCloseTo(90)
    expect(routeGeometryAtProgress([[0, 0], [-1, 0]], 0.5).bearing).toBeCloseTo(270)
    expect(routeGeometryAtProgress([[0, 0], [0, 1]], 0.5).bearing).toBeCloseTo(0)
    expect(routeGeometryAtProgress([[0, 0], [0, -1]], 0.5).bearing).toBeCloseTo(180)
  })

  it('동쪽으로 날짜변경선을 지나는 선을 양쪽 경계에서 분할한다', () => {
    expect(routeLineGeometry([[170, 10], [-170, 20]])).toEqual({
      type: 'MultiLineString',
      coordinates: [
        [[170, 10], [180, 15]],
        [[-180, 15], [-170, 20]],
      ],
    })
  })

  it('동쪽 날짜변경선 보간은 짧은 방향의 위치·방위·지나온 좌표를 반환한다', () => {
    const result = routeGeometryAtProgress([[170, 0], [-170, 0]], 0.5)
    expect(Math.abs(result.position[0])).toBeCloseTo(180)
    expect(result.position[1]).toBeCloseTo(0)
    expect(result.bearing).toBeCloseTo(90)
    expect(result.traveledCoordinates).toEqual([[170, 0], result.position])
  })

  it('서쪽으로 날짜변경선을 지나는 선도 양쪽 경계에서 분할한다', () => {
    expect(routeLineGeometry([[-170, 20], [170, 10]])).toEqual({
      type: 'MultiLineString',
      coordinates: [
        [[-170, 20], [-180, 15]],
        [[180, 15], [170, 10]],
      ],
    })
  })

  it('서쪽 날짜변경선 보간도 짧은 방향의 위치·방위·지나온 좌표를 반환한다', () => {
    const result = routeGeometryAtProgress([[-170, 0], [170, 0]], 0.5)
    expect(Math.abs(result.position[0])).toBeCloseTo(180)
    expect(result.position[1]).toBeCloseTo(0)
    expect(result.bearing).toBeCloseTo(270)
    expect(result.traveledCoordinates).toEqual([[-170, 0], result.position])
  })

  it('중복 제거·비유한 값 거부·진행률 clamp를 각각 보장한다', () => {
    expect(routeGeometryAtProgress([[0, 0], [0, 0], [4, 0]], 0.5).position).toEqual([2, 0])
    expect(() => routeGeometryAtProgress([[0, 0], [Number.POSITIVE_INFINITY, 0]], 0.5))
      .toThrow('항로 좌표')
    expect(routeGeometryAtProgress([[0, 0], [4, 0]], -0.1).position).toEqual([0, 0])
    expect(routeGeometryAtProgress([[0, 0], [4, 0]], 1.1).position).toEqual([4, 0])
  })
})

describe('항로 출처 allowlist', () => {
  it('searoute/marnet을 display-only 정본 메타데이터로 반환한다', () => {
    expect(getKnownRouteSource('searoute/marnet')).toEqual({
      id: 'searoute/marnet',
      label: 'Eurostat SeaRoute 해상 경로망',
      attribution: '해상 경로망 © Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)',
      license: 'Eurostat SeaRoute: EUPL-1.2; searoute: Apache-2.0',
      sourceUrl: 'https://github.com/eurostat/searoute',
      displayOnly: true,
    })
  })

  it('서버가 보낸 알 수 없는 출처나 자유 attribution을 허용하지 않는다', () => {
    expect(getKnownRouteSource('unknown')).toBeNull()
    expect(getKnownRouteSource('<script>임의 출처</script>')).toBeNull()
  })
})

describe('명시적 계획 waypoint geometry', () => {
  const source = getKnownRouteSource('searoute/marnet')!

  it('provider의 순서·label·좌표와 출처를 그대로 보존한다', () => {
    const route = createWaypointRouteGeometry([
      { order: 10, coordinate: [170, 10], label: '출발' },
      { order: 20, coordinate: [-179, 12], label: '계획점' },
      { order: 30, coordinate: [-170, 15], label: '도착' },
    ], source)
    expect(route.source).toBe(source)
    expect(route.coordinates).toEqual([[170, 10], [-179, 12], [-170, 15]])
    expect(route.derivation).toEqual({ kind: 'WAYPOINT', waypoints: [
      { order: 10, coordinate: [170, 10], label: '출발' },
      { order: 20, coordinate: [-179, 12], label: '계획점' },
      { order: 30, coordinate: [-170, 15], label: '도착' },
    ] })
    expect(routeLineGeometry(route.coordinates).type).toBe('MultiLineString')
  })

  it('invalid 순서·중복 좌표·출처 누락을 fallback 없이 거부한다', () => {
    expect(() => createWaypointRouteGeometry([
      { order: 2, coordinate: [0, 0] }, { order: 1, coordinate: [1, 0] },
    ], source)).toThrow('순서')
    expect(() => createWaypointRouteGeometry([
      { order: 1, coordinate: [0, 0] }, { order: 2, coordinate: [0, 0] },
    ], source)).toThrow('중복')
    expect(() => createWaypointRouteGeometry([
      { order: 1, coordinate: [0, 0] }, { order: 2, coordinate: [181, 0] },
    ], source)).toThrow('좌표')
    expect(() => createWaypointRouteGeometry([
      { order: 1, coordinate: [0, 0] }, { order: 2, coordinate: [1, 0] },
    ], null as never)).toThrow('출처')
  })
})
