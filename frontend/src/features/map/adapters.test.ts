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

/**
 * 정박 중인 배 옆의 항만 (`#1933`).
 *
 * 종전에는 **진행 중 항차의 두 끝만** 핀을 세웠다(`#1882`). 그래서 배가 정박해 있으면
 * 항차가 없어 핀이 하나도 서지 않았고, 대시보드에 정박 3척이 있어도 지도에 항만이
 * 없었다 — 정박은 **항만에서 일어나는 일**이라 그 자리를 비우면 「이 배가 어디 있나」의
 * 답이 반쪽이 된다.
 *
 * ⚠️ 이 핀은 **접안을 주장하지 않는다.** 서버가 주는 것은 `underwayState`뿐이고 어느
 * 부두인지는 이 제품에 없다 — 핀이 말하는 것은 「여기 이 항만이 있다」다.
 */
describe('정박 중인 배 옆의 항만 핀 (#1933)', () => {
  const BUSAN = { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.04 }
  const SINGAPORE = { locode: 'SGSIN', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.26, lon: 103.8 }
  const ULSAN = { locode: 'KRUSN', name: 'ULSAN', name_ko: '울산', country_code: 'KR', lat: 35.5, lon: 129.38 }

  const moored = (lat: string, lon: string) => ({
    id: 'v1', name: '샘플 벌크선', lat, lon, ytdRating: null,
    underwayState: 'NOT_UNDER_WAY' as const, courseDeg: null, route: null,
  })

  it('정박한 배 근처의 항만에 핀을 세운다', () => {
    const { ports } = adaptFleetMap([moored('35.12', '129.06')], [], [BUSAN, SINGAPORE])
    expect(ports).toHaveLength(1)
    expect(ports[0].role).toBe('berth')
    expect(ports[0].label).toBe('부산')
    // 장면이 있는 항만이라 **누를 수 있다** — 눌러 항만으로 들어간다.
    expect(ports[0].enterable).toBe(true)
    expect(ports[0].id).toContain('KRPUS')
  })

  it('운항 중인 배 옆에는 세우지 않는다', () => {
    const underway = { ...moored('35.12', '129.06'), underwayState: 'UNDER_WAY' as const }
    expect(adaptFleetMap([underway], [], [BUSAN]).ports).toHaveLength(0)
  })

  it('가까운 항만이 없으면 지어내지 않는다', () => {
    // 태평양 한가운데. 억지로 가장 가까운 항을 붙이면 **없는 사실을 주장하는 것**이다.
    expect(adaptFleetMap([moored('20', '170')], [], [BUSAN, SINGAPORE]).ports).toHaveLength(0)
  })

  it('장면이 없는 항만은 그림으로 남는다', () => {
    // 눌러도 아무 일이 없는 버튼은 고장으로 읽힌다 — 저장소가 담은 장면은 둘뿐이다.
    const { ports } = adaptFleetMap([moored('35.48', '129.4')], [], [ULSAN])
    expect(ports[0].label).toBe('울산')
    expect(ports[0].enterable).toBe(false)
  })

  it('둘 중 더 가까운 항만을 고른다', () => {
    const { ports } = adaptFleetMap([moored('35.45', '129.35')], [], [BUSAN, ULSAN])
    expect(ports[0].label).toBe('울산')
  })
})

/**
 * 항차 끝의 항만도 **장면이 있으면 들어갈 수 있다** (`#1933`).
 *
 * 종전에는 좌표가 항만표와 **정확히** 같을 때만 LOCODE를 찾았다. 항차 좌표는 사용자가
 * 넣은 값이라 소수점이 어긋나기 쉽고, 그래서 싱가포르처럼 장면이 있는 항이 그림으로
 * 남았다 — 들어갈 곳이 있는데 문이 없었다.
 */
describe('항차 끝 항만의 LOCODE 해석 (#1933)', () => {
  const SINGAPORE = { locode: 'SGSIN', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.26, lon: 103.8 }
  const withRoute = (arrivalLat: string, arrivalLon: string, name: string | null) => ({
    id: 'v1', name: '샘플 벌크선', lat: '10', lon: '110', ytdRating: null,
    underwayState: 'UNDER_WAY' as const, courseDeg: null,
    route: {
      departureLat: '35.1', departureLon: '129.04', arrivalLat, arrivalLon,
      departurePortName: null, arrivalPortName: name,
    },
  })

  it('이름이 같으면 찾는다', () => {
    const { ports } = adaptFleetMap([withRoute('1.2833', '103.8517', 'SINGAPORE')], [], [SINGAPORE])
    const arrival = ports.find((port) => port.role === 'destination')
    expect(arrival?.enterable).toBe(true)
    expect(arrival?.id).toContain('SGSIN')
  })

  it('이름이 없어도 그 자리의 항만으로 찾는다', () => {
    const { ports } = adaptFleetMap([withRoute('1.2833', '103.8517', null)], [], [SINGAPORE])
    expect(ports.find((port) => port.role === 'destination')?.enterable).toBe(true)
  })

  it('먼 좌표에는 붙이지 않는다', () => {
    const { ports } = adaptFleetMap([withRoute('20', '170', null)], [], [SINGAPORE])
    expect(ports.find((port) => port.role === 'destination')?.enterable).toBe(false)
  })
})
