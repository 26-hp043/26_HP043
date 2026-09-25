import { describe, expect, it } from 'vitest'
import { adaptAnnualMapGeometry, adaptComparisonRoutes, adaptFleetMap } from './adapters'
import { getKnownRouteSource } from './routeGeometry'
import type { FleetVessel } from '../fleet/types'

const vessel = (lat: string | null, lon: string | null): FleetVessel => ({
  id: 'v1', name: 'BLUE', imoNumber: '1234567', shipType: 'BULK_CARRIER',
  ytdRating: null, ytdAttainedCii: null, ytdRequiredCii: null, riskLevel: null,
  lat, lon, courseDeg: null, underwayState: null, detailStatus: null, route: null,
  positionUpdatedAt: null, isCiiApplicableHint: true, grossTonnage: '10000',
  dataAvailable: false, unavailableReason: 'NO_DATA', riskReasons: [],
  daysToD: null, daysToDReason: 'NO_DATA',
})

describe('공용 map adapter', () => {
  it('Fleet 정상·legacy 문자열 좌표는 받고 null·invalid는 버리며 추정하지 않는다', () => {
    expect(adaptFleetMap([vessel('35.1', '129.0')], []).positions).toHaveLength(1)
    expect(adaptFleetMap([vessel(null, null)], []).positions).toHaveLength(0)
    expect(adaptFleetMap([vessel('91', '129')], []).positions).toHaveLength(0)
  })

  it('Fleet 항만 marker는 항차 양 끝을 표시하고 서버 이름을 우선한다', () => {
    const routed = { ...vessel('35.1', '129'), route: { departureLat: '35.1', departureLon: '129', arrivalLat: '1.2', arrivalLon: '103.8', departurePortName: null, arrivalPortName: null } }
    const ports = [
      { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129 },
      { locode: 'SGSIN', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2, lon: 103.8 },
    ]
    expect(adaptFleetMap([routed], [], ports).ports.map(({ role, label }) => [role, label]))
      .toEqual([['departure', '부산'], ['destination', '싱가포르']])
    expect(adaptFleetMap([routed], [], []).ports.map(({ role, label }) => [role, label]))
      .toEqual([['departure', ''], ['destination', '']])
    const named = { ...routed, route: { ...routed.route, departurePortName: 'Busan', arrivalPortName: 'Singapore' } }
    expect(adaptFleetMap([named], [], ports).ports.map(({ label }) => label))
      .toEqual(['Busan', 'Singapore'])
  })

  it('Comparison no-route·invalid·반쪽 경유점은 빈 항로 또는 직항만 반환한다', () => {
    const base = { currentLat: '35.1', currentLon: '129', destinationLat: '1.2', destinationLon: '103.8', destinationName: '', detourWaypointLat: '', detourWaypointLon: '', detourWaypointName: '' }
    expect(adaptComparisonRoutes({ ...base, currentLat: '' })).toEqual([])
    expect(adaptComparisonRoutes({ ...base, currentLat: 'NaN' })).toEqual([])
    expect(adaptComparisonRoutes({ ...base, detourWaypointLat: '21' })).toHaveLength(1)
    expect(adaptComparisonRoutes({ ...base, detourWaypointLat: '21', detourWaypointLon: '-157' })).toHaveLength(2)
  })

  it('Annual은 정상 source만 보존하고 source 누락·snapshot mismatch를 거부한다', () => {
    const source = getKnownRouteSource('searoute/marnet')!
    const available = { status: 'available' as const, snapshotId: 's1', routes: [{ snapshotVoyageId: 'v1', coordinates: [[129, 35], [103, 1]] as const, source }] }
    expect(adaptAnnualMapGeometry('s1', available)).toEqual(available)
    expect(() => adaptAnnualMapGeometry('s2', available)).toThrow('스냅샷')
    expect(() => adaptAnnualMapGeometry('s1', { ...available, routes: [{ ...available.routes[0], source: { ...source, id: 'unknown' } }] } as never)).toThrow('출처')
    expect(() => adaptAnnualMapGeometry('s1', { ...available, routes: [{ ...available.routes[0], coordinates: [[200, 35]] }] } as never)).toThrow('좌표')
  })

  it('Annual의 명시적 WAYPOINT derivation을 보존하고 coordinates fallback을 만들지 않는다', () => {
    const source = getKnownRouteSource('searoute/marnet')!
    const waypointRoute = {
      snapshotVoyageId: 'v1', source,
      coordinates: [[0, 0], [99, 0]] as const,
      derivation: { kind: 'WAYPOINT' as const, waypoints: [
        { order: 1, coordinate: [170, 0] as const, label: '출발' },
        { order: 2, coordinate: [-170, 0] as const, label: '도착' },
      ] },
    }
    const adapted = adaptAnnualMapGeometry('s1', { status: 'available', snapshotId: 's1', routes: [waypointRoute] })
    expect(adapted.status).toBe('available')
    if (adapted.status === 'available') {
      expect(adapted.routes[0].coordinates).toEqual([[170, 0], [-170, 0]])
      expect(adapted.routes[0].derivation).toEqual(waypointRoute.derivation)
    }
    expect(() => adaptAnnualMapGeometry('s1', {
      status: 'available', snapshotId: 's1', routes: [{ ...waypointRoute, source: undefined }],
    } as never)).toThrow('출처')
    expect(() => adaptAnnualMapGeometry('s1', {
      status: 'available', snapshotId: 's1', routes: [{
        ...waypointRoute,
        derivation: { kind: 'WAYPOINT', waypoints: [{ order: 2, coordinate: [0, 0] }, { order: 1, coordinate: [1, 0] }] },
      }],
    } as never)).toThrow('좌표')
    expect(() => adaptAnnualMapGeometry('s1', {
      status: 'available', snapshotId: 's1', routes: [{ ...waypointRoute, derivation: { kind: 'GREAT_CIRCLE' } }],
    } as never)).toThrow('좌표')
  })
})
