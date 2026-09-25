import { describe, expect, it } from 'vitest'
import type { SnapshotVoyage } from '../types'
import { getKnownRouteSource } from '../../map/routeGeometry'
import { adaptSnapshotVoyages } from './snapshotVoyageModel'

const row = (overrides: Partial<SnapshotVoyage> = {}): SnapshotVoyage => ({
  snapshot_voyage_id: 'snapshot-voyage-1', original_voyage_id: null, voyage_no: null,
  status_at_snapshot: 'PLANNED', distance_nm: null, speed_kn: null,
  fuel_uses: [{ fuel_type: 'VLSFO', fuel_ton: '12.3400', cf_used: '3.114000' }],
  annual_inclusion_policy: 'INCLUDED', ...overrides,
})

describe('snapshot voyage 시각화 모델', () => {
  it('null distance/speed와 fuel 계산 truth를 재계산 없이 복사하고 route를 추정하지 않는다', () => {
    const input = row()
    const [voyage] = adaptSnapshotVoyages([input])
    expect(voyage.calculation).toEqual({
      distanceNm: null, speedKnots: null,
      fuelUses: [{ fuelType: 'VLSFO', fuelTon: '12.3400', cfUsed: '3.114000' }],
      annualInclusionPolicy: 'INCLUDED',
    })
    expect(voyage.animation).toEqual({ route: null, visualDurationMs: null })
  })

  it('snapshot voyage id가 정확히 같은 route의 source·waypoint·playback metadata만 보존한다', () => {
    const source = getKnownRouteSource('searoute/marnet')!
    const route = {
      snapshotVoyageId: 'snapshot-voyage-1', playbackDurationMs: 4_000,
      coordinates: [[170, 0], [-170, 0]] as const, source,
      derivation: { kind: 'WAYPOINT' as const, waypoints: [
        { order: 1, coordinate: [170, 0] as const }, { order: 2, coordinate: [-170, 0] as const },
      ] },
    }
    const [voyage] = adaptSnapshotVoyages([row()], { status: 'available', snapshotId: 'snapshot-1', routes: [route] })
    expect(voyage.animation.route).toBe(route)
    expect(voyage.animation.visualDurationMs).toBe(4_000)
    expect(voyage.animation.route?.source).toBe(source)
    expect(voyage.animation.route?.derivation).toBe(route.derivation)
    expect(adaptSnapshotVoyages([row({ snapshot_voyage_id: 'other' })], {
      status: 'available', snapshotId: 'snapshot-1', routes: [route],
    })[0].animation).toEqual({ route: null, visualDurationMs: null })
  })

  it('항차가 없거나 duration이 없으면 synthetic 항차·시간을 만들지 않는다', () => {
    expect(adaptSnapshotVoyages([])).toEqual([])
    const source = getKnownRouteSource('searoute/marnet')!
    const [voyage] = adaptSnapshotVoyages([row()], {
      status: 'available', snapshotId: 'snapshot-1', routes: [{
        snapshotVoyageId: 'snapshot-voyage-1', coordinates: [[0, 0], [1, 0]], source,
      }],
    })
    expect(voyage.animation.visualDurationMs).toBeNull()
  })
})
