import { describe, expect, it } from 'vitest'
import type { AnnualSimulationResult } from '../types'
import { createVisualizationModel } from './model'

const RESULT: AnnualSimulationResult = {
  simulation_id: 'simulation-1',
  calculation_run_id: 'calculation-1',
  deterministic: {
    projected_attained_cii: '5.0248000000',
    projected_rating: 'C',
    completed_voyage_count: 1,
    remaining_voyage_count: 1,
    completed_M_gco2: '1',
    completed_W_capacity_nm: '1',
    planned_M_gco2: '1',
    planned_W_capacity_nm: '1',
  },
  monte_carlo: {
    rng_metadata: {
      seed_entropy: '1',
      bit_generator: 'PCG64DXSM',
      numpy_version: '2',
      python_version: '3',
      platform: 'test',
    },
    runs: 1000,
    rating_probabilities: { A: '0.0100', B: '0.0200', C: '0.0300', D: '0.0400', E: '0.9000' },
    target_success_probability: '0.0600',
    target_rating: 'C',
    p10: '1',
    p50: '2',
    p90: '3',
    mean_cii: '2',
  },
  risk_level: 'HIGH',
  sensitivity_analysis: { interaction_note: '' },
  snapshot: { snapshot_id: 'snapshot-1', created_at: '2026-09-24T00:00:00Z', voyage_count: 2 },
  warnings: [],
}

describe('연간 시뮬레이션 시각화 모델', () => {
  it('서버 수치 문자열을 그대로 전달하고 좌표가 없는 상태를 표시한다', () => {
    const model = createVisualizationModel(RESULT)

    expect(model.projectedAttainedCii).toBe('5.0248000000')
    expect(model.targetSuccessProbability).toBe('0.0600')
    expect(model.ratingProbabilities).toBe(RESULT.monte_carlo.rating_probabilities)
    expect(model.mapGeometry).toEqual({
      status: 'unavailable',
      reason: 'coordinates_not_provided',
    })
  })

  it('다른 실행의 스냅샷 좌표를 결합하지 않는다', () => {
    expect(() =>
      createVisualizationModel(RESULT, {
        status: 'available',
        snapshotId: 'snapshot-2',
        routes: [],
      }),
    ).toThrow('지도 좌표의 스냅샷이 시뮬레이션 결과와 다릅니다.')
  })
})
