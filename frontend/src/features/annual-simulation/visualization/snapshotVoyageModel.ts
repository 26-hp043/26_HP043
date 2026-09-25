import type { SnapshotVoyage } from '../types'
import type { MapGeometry, SnapshotRouteGeometry } from './model'

export interface SimulationFuelUse {
  readonly fuelType: string
  readonly fuelTon: number | string | null
  readonly cfUsed: number | string | null
}

export interface SimulationVoyage {
  readonly snapshotVoyageId: string
  readonly originalVoyageId: string | null
  readonly voyageNo: string | null
  readonly statusAtSnapshot: string
  readonly calculation: {
    readonly distanceNm: number | string | null
    readonly speedKnots: number | string | null
    readonly fuelUses: readonly SimulationFuelUse[]
    readonly annualInclusionPolicy: string
  }
  readonly animation: {
    readonly route: SnapshotRouteGeometry | null
    /** 실제 항해시간이 아니라 provider가 명시한 시각화용 상대 재생 길이다. */
    readonly visualDurationMs: number | null
  }
}

/** snapshot 계산 truth를 복사하고, 별도 provider route가 있을 때만 animation 데이터를 결합한다. */
export function adaptSnapshotVoyages(
  rows: readonly SnapshotVoyage[],
  geometry: MapGeometry = { status: 'unavailable', reason: 'coordinates_not_provided' },
): readonly SimulationVoyage[] {
  const routes = geometry.status === 'available'
    ? new Map(geometry.routes.map((route) => [route.snapshotVoyageId, route]))
    : new Map<string, SnapshotRouteGeometry>()
  return rows.map((row) => {
    const route = routes.get(row.snapshot_voyage_id) ?? null
    const duration = route?.playbackDurationMs
    return {
      snapshotVoyageId: row.snapshot_voyage_id,
      originalVoyageId: row.original_voyage_id,
      voyageNo: row.voyage_no,
      statusAtSnapshot: row.status_at_snapshot,
      calculation: {
        distanceNm: row.distance_nm,
        speedKnots: row.speed_kn,
        fuelUses: row.fuel_uses.map((fuel) => ({
          fuelType: fuel.fuel_type, fuelTon: fuel.fuel_ton, cfUsed: fuel.cf_used,
        })),
        annualInclusionPolicy: row.annual_inclusion_policy,
      },
      animation: {
        route,
        visualDurationMs: duration !== undefined && duration !== null && Number.isFinite(duration) && duration > 0
          ? duration
          : null,
      },
    }
  })
}
