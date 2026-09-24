import { describe, expect, it } from 'vitest'
import { routeGeometryAtProgress, type RouteCoordinate } from './routeGeometry'

describe('전체 항로 진행 위치 계산', () => {
  const unevenRoute: RouteCoordinate[] = [[0, 0], [1, 0], [10, 0]]

  it('좌표점 개수가 아니라 누적 대권거리를 기준으로 일정하게 이동한다', () => {
    const quarter = routeGeometryAtProgress(unevenRoute, 0.25)
    const middle = routeGeometryAtProgress(unevenRoute, 0.5)
    const threeQuarters = routeGeometryAtProgress(unevenRoute, 0.75)

    expect(quarter.position).toEqual([2.5, 0])
    expect(middle.position).toEqual([5, 0])
    expect(threeQuarters.position).toEqual([7.5, 0])
  })

  it('시작, 중간, 끝의 위치와 지나온 항로를 반환한다', () => {
    const start = routeGeometryAtProgress(unevenRoute, 0)
    const middle = routeGeometryAtProgress(unevenRoute, 0.5)
    const end = routeGeometryAtProgress(unevenRoute, 1)

    expect(start).toEqual({ position: [0, 0], bearing: 90, traveledCoordinates: [[0, 0]] })
    expect(middle.bearing).toBeCloseTo(90)
    expect(middle.traveledCoordinates).toEqual([[0, 0], [1, 0], [5, 0]])
    expect(end).toEqual({
      position: [10, 0],
      bearing: 90,
      traveledCoordinates: [[0, 0], [1, 0], [10, 0]],
    })
  })

  it('연속 중복 좌표를 제거하고 유효한 다음 구간으로 진행한다', () => {
    const geometry = routeGeometryAtProgress([[0, 0], [0, 0], [0, 0], [2, 0]], 0.5)

    expect(geometry.position).toEqual([1, 0])
    expect(geometry.bearing).toBeCloseTo(90)
    expect(geometry.traveledCoordinates).toEqual([[0, 0], [1, 0]])
  })

  it('모든 좌표가 중복이면 명시적으로 거부한다', () => {
    expect(() => routeGeometryAtProgress([[129, 35], [129, 35]], 0.5))
      .toThrow('항로에는 서로 다른 좌표가 두 개 이상 필요합니다.')
  })

  it('범위를 벗어난 진행률을 시작과 끝으로 제한한다', () => {
    expect(routeGeometryAtProgress(unevenRoute, -1).position).toEqual([0, 0])
    expect(routeGeometryAtProgress(unevenRoute, 2).position).toEqual([10, 0])
  })
})
