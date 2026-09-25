import type { Rating, RiskLevel } from '../../voyage-cii/types'
import type { AnnualSimulationResult } from '../types'
import type { RouteGeometry } from '../../map/routeGeometry'
import type { MapRenderer, MapRendererSession } from '../../map/renderer'
import { adaptAnnualMapGeometry } from '../../map/adapters'

/** 향후 스냅샷에 결부된 지리 데이터 공급자가 제공할 선. */
export interface SnapshotRouteGeometry extends RouteGeometry {
  readonly snapshotVoyageId: string
  /** 시각화 전용 상대 길이이며 실제 항해 시간으로 해석하지 않는다. */
  readonly playbackDurationMs?: number | null
  readonly startedAt?: string | null
  readonly endedAt?: string | null
  readonly vesselName?: string | null
  readonly departureName?: string | null
  readonly arrivalName?: string | null
  /** provider가 실제 항차에서 제공한 경우에만 wake 판단에 쓴다. */
  readonly speedKnots?: number | null
  /** 상대 강도도 provider가 산출한 0~1 값이며 화면이 배출량에서 재계산하지 않는다. */
  readonly emission?: {
    readonly co2Value: string
    readonly co2Unit: 'gCO₂' | 'kgCO₂' | 'tCO₂'
    readonly intensityValue?: string | null
    readonly intensityUnit?: string | null
    readonly relativeIntensity?: number | null
  } | null
}

/** API 응답과 별도로, 같은 immutable snapshot의 실제 좌표만 공급하는 미래 provider 경계다. */
export interface AnnualMapGeometryProvider {
  load(result: AnnualSimulationResult, signal: AbortSignal): Promise<MapGeometry>
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
  if (!result?.deterministic || !result.monte_carlo || !result.snapshot) {
    throw new Error('시각화에 필요한 연간 시뮬레이션 응답 block이 없습니다.')
  }
  const adaptedMapGeometry = adaptAnnualMapGeometry(result.snapshot.snapshot_id, mapGeometry)

  return {
    simulationId: result.simulation_id,
    snapshotId: result.snapshot.snapshot_id,
    projectedAttainedCii: result.deterministic.projected_attained_cii,
    projectedRating: result.deterministic.projected_rating,
    targetSuccessProbability: result.monte_carlo.target_success_probability,
    ratingProbabilities: result.monte_carlo.rating_probabilities,
    riskLevel: result.risk_level,
    mapGeometry: adaptedMapGeometry,
  }
}

/** 지도 라이브러리의 수명 주기를 화면에서 분리하는 최소 계약. */
export type AnnualSimulationRenderer = MapRenderer<AnnualSimulationVisualizationModel & { readonly mode: 'playback' }>
export type AnnualSimulationRendererSession = MapRendererSession<AnnualSimulationVisualizationModel & { readonly mode: 'playback' }>
