import type { Rating, RiskLevel } from '../voyage-cii/types'

/**
 * 기능③(연간 CII 시뮬레이션)의 요청·응답 타입 — `API_SPEC §6.1` (#442).
 *
 * ## 서버 계약을 그대로 옮긴다
 *
 * v1(`#157`)은 엔진·API가 없던 시점의 **목업 형태**였다 — 월별 집계 12행과 합계를
 * 담았는데, `#63`·`#64`가 들어온 지금 서버는 **그것을 주지 않는다.** 서버가 주는 것은
 * 결정론 예측(`PRD §12.3`) · Monte Carlo 분포(`§12.4`) · 민감도(`§12.6`) · 스냅샷이다.
 *
 * 화면이 없는 필드를 만들어 두면 **어디선가 채워야 하고, 채우는 곳이 화면이 되면**
 * 계산이 두 곳에 생긴다. 그래서 서버 계약에 정확히 맞춘다.
 *
 * ## Layer 1 값은 문자열이다
 *
 * `API_SPEC §1.7` `[ORACLE-C-1]`. 화면에서 `parseFloat`·`Number`로 되돌리지 않는다 —
 * 되돌리는 순간 문자열 직렬화로 지킨 정밀도가 사라진다.
 *
 * **확률도 문자열이다.** 서버 구현이 `Decimal`을 문자열로 내보낸다
 * (`services/annual_simulation.py`). `API_SPEC §6.1` 예시가 숫자로 적힌 것은 예시
 * 표기이며 실제 응답은 문자열이다 — 구현체와 대조해 확인했다.
 */

/** 실행 요청 — `API_SPEC §6.1` 요청 Body. */
export interface AnnualSimulationRequest {
  vessel_id: string
  regulation_year: number
  /** `PRD §12.8` — **E는 불가**하다. 목표가 최하위 등급이면 「달성」이 의미를 잃는다. */
  target_rating: 'A' | 'B' | 'C' | 'D'
  /** 1000~10000. 기본 5000. */
  simulation_runs: number
  /** 미지정 시 서버가 128-bit entropy를 만들고 `rng_metadata`로 돌려준다. */
  random_seed?: number | string
  /** enum: `DEFAULT`. 분포는 `simulation_parameter` 테이블이 소유한다(`#434`). */
  distribution_profile?: string
}

/** 결정론 예측 — `PRD §12.3`. Monte Carlo와 달리 **같은 입력이면 항상 같은 값**이다. */
export interface DeterministicBlock {
  /** Layer 1 */
  projected_attained_cii: string
  projected_rating: Rating
  /** **숫자** — 집계된 실적 항차 수 */
  completed_voyage_count: number
  /** **숫자** — 남은 계획 항차 수 */
  remaining_voyage_count: number
  /** Layer 1 — 분자·분모를 그대로 노출한다. 화면이 다시 나누지 않는다 */
  completed_M_gco2: string
  completed_W_capacity_nm: string
  planned_M_gco2: string
  planned_W_capacity_nm: string
}

/**
 * 재현성 메타데이터 — `TECH_SPEC §5.2`.
 *
 * **이 블록이 없으면 「이 seed로 다시 실행」이 거짓말이 된다.** 화면이 보관·표시해야
 * 하는 이유가 그것이다.
 */
export interface RngMetadata {
  seed_entropy: string
  bit_generator: string
  numpy_version: string
  python_version: string
  platform: string
}

/** Monte Carlo 분포 — `PRD §12.4`·`§12.5`. */
export interface MonteCarloBlock {
  rng_metadata: RngMetadata
  /** **숫자** */
  runs: number
  /** 등급별 확률. 값은 문자열이다(위 docstring). */
  rating_probabilities: Record<Rating, string>
  /** 목표 등급 **이상**을 달성할 확률 */
  target_success_probability: string
  target_rating: Rating
  p10: string
  p50: string
  p90: string
  mean_cii: string
}

/** 민감도 항목 1건 — `PRD §12.6`. 변수마다 담기는 필드가 다르다. */
export interface SensitivityEntry {
  /** Layer 1 */
  projected_cii: string
  /** `C→B` 형태. 서버가 만든 문자열을 그대로 쓴다 */
  rating_change: string
  /** 확률 변화. 거리·항차 변수에는 없다 */
  target_probability_change?: string
  /** 연료 CF 대체 시나리오에만 있다 */
  alternative_fuel?: string
  alternative_cf?: string
  co2_change?: string
}

/**
 * 민감도 분석 — `PRD §12.6` · `API_SPEC §6.1`.
 *
 * `interaction_note`는 **`ORACLE-M-3`이 응답 포함을 지정한 필수 항목**이다. 「각 변수의
 * 개별 효과만 표시한다」는 사실을 빼면, 사용자가 두 변수를 함께 조정했을 때의 결과를
 * 이 표에서 읽으려 한다.
 */
export interface SensitivityAnalysis {
  interaction_note: string
  speed_minus_1kn?: SensitivityEntry
  speed_plus_1kn?: SensitivityEntry
  fuel_minus_10pct?: SensitivityEntry
  fuel_plus_10pct?: SensitivityEntry
  distance_minus_5pct?: SensitivityEntry
  distance_plus_5pct?: SensitivityEntry
  fuel_cf_alternative?: SensitivityEntry
  voyage_minus_1?: SensitivityEntry
  voyage_plus_1?: SensitivityEntry
}

/** 실행 당시 데이터 스냅샷 — `TECH_SPEC §11`. */
export interface SnapshotBlock {
  snapshot_id: string
  created_at: string
  /** **숫자** */
  voyage_count: number
}

/** `POST /annual-simulations` 응답의 `data`. */
export interface AnnualSimulationResult {
  simulation_id: string
  calculation_run_id: string
  deterministic: DeterministicBlock
  monte_carlo: MonteCarloBlock
  /** `PRD §9.4.2` — **목표 달성 확률 기반**이다. 화면이 다시 판정하지 않는다 */
  risk_level: RiskLevel
  sensitivity_analysis: SensitivityAnalysis
  snapshot: SnapshotBlock
  warnings: string[]
  /**
   * 실제 계산이 아니라 예시 데이터임을 나타낸다.
   *
   * **서버 응답에는 이 필드가 없다** — demo provider만 `true`로 채운다. 화면이 배지를
   * 상수로 박지 않고 **응답에서 판단**하게 하려고 남겨 둔 자리다(`#157` 완료 기준).
   */
  is_sample_data?: boolean
}

/** provider 경계 — 화면은 이 인터페이스만 안다 (`#134`와 같은 모양). */
export interface AnnualSimulationProvider {
  run(request: AnnualSimulationRequest): Promise<AnnualSimulationResult>
}
