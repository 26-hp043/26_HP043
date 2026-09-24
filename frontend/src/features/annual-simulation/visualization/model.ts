import type { Rating, RiskLevel } from '../../voyage-cii/types'
import type { AnnualSimulationResult } from '../types'

/** GeoJSON 순서: 경도, 위도. 계산 거리와 무관한 표시용 좌표다. */
export type MapCoordinate = readonly [longitude: number, latitude: number]

/** 향후 스냅샷에 결부된 지리 데이터 공급자가 제공할 선. */
export interface SnapshotRouteGeometry {
  readonly snapshotVoyageId: string
  readonly coordinates: readonly MapCoordinate[]
}

/**
 * 현재 `API_SPEC §6.1`·`§6.3`에는 좌표가 없다. 없는 경로를 거리·속력으로 만들지 않는다.
 * 좌표 공급 계약이 생기면 반드시 같은 스냅샷의 항차를 참조해야 한다.
 */
export type MapGeometry =
  | { readonly status: 'unavailable'; readonly reason: 'coordinates_not_provided' }
  | {
      readonly status: 'available'
      readonly snapshotId: string
      readonly routes: readonly SnapshotRouteGeometry[]
    }

/**
 * 렌더러가 읽는 장면 데이터. 수치는 서버 문자열 그대로 전달하며 여기서 계산하지 않는다.
 * MapLibre·Three·full 3D 구현은 모두 같은 모델을 소비한다.
 */
export interface AnnualSimulationVisualizationModel {
  readonly simulationId: string
  readonly snapshotId: string
  readonly projectedAttainedCii: string
  readonly projectedRating: Rating
  readonly targetSuccessProbability: string
  readonly ratingProbabilities: Readonly<Record<Rating, string>>
  readonly riskLevel: RiskLevel
  readonly mapGeometry: MapGeometry
}

/** 도메인 결과에서 값을 복사할 뿐 CII·확률·등급·감축량을 다시 산출하지 않는다. */
export function createVisualizationModel(
  result: AnnualSimulationResult,
  mapGeometry: MapGeometry = { status: 'unavailable', reason: 'coordinates_not_provided' },
): AnnualSimulationVisualizationModel {
  if (mapGeometry.status === 'available' && mapGeometry.snapshotId !== result.snapshot.snapshot_id) {
    throw new Error('지도 좌표의 스냅샷이 시뮬레이션 결과와 다릅니다.')
  }

  return {
    simulationId: result.simulation_id,
    snapshotId: result.snapshot.snapshot_id,
    projectedAttainedCii: result.deterministic.projected_attained_cii,
    projectedRating: result.deterministic.projected_rating,
    targetSuccessProbability: result.monte_carlo.target_success_probability,
    ratingProbabilities: result.monte_carlo.rating_probabilities,
    riskLevel: result.risk_level,
    mapGeometry,
  }
}

/** 지도 라이브러리의 수명 주기를 화면에서 분리하는 최소 계약. */
export interface AnnualSimulationRenderer {
  mount(target: HTMLElement, model: AnnualSimulationVisualizationModel): AnnualSimulationRendererSession
}

export interface AnnualSimulationRendererSession {
  update(model: AnnualSimulationVisualizationModel): void
  destroy(): void
}
