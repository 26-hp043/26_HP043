import type { CapacityBasis, Rating, RiskLevel } from '../voyage-cii/types'

/**
 * 기능②(운항 중 시나리오 비교)의 요청·응답 타입.
 *
 * ## ⚠️ 임시 정의다 — `#151` 확정 후 정본에 맞춘다
 *
 * **`API_SPEC §5.1`의 예시값을 참조하지 않았다.** `fuel_ton`·`co2_emission_ton`·
 * `attained_cii`가 서로 어긋나 있고 `weather_model`도 요청/응답이 맞지 않는다.
 * 정정은 `#151`이 처리하며 그 전까지 `§5.1`은 기능②의 타입 정본이 아니다.
 *
 * 필드명은 **`PRD §7.5 VoyageScenario`**(상위 문서)에서 가져왔다 — `scenario_type` ·
 * `distance_nm` · `speed_kn` · `duration_hours` · `fuel_ton` · `estimated_rating` ·
 * `risk_level`. `AGENTS §3` 우선순위상 `API_SPEC`이 미확정인 지금 `PRD`가 기준이다.
 *
 * ## Layer 1 값은 문자열이다
 *
 * `#134`가 기능①에서 확정한 표현 규칙을 그대로 따른다(`API_SPEC §1.7`
 * `[ORACLE-C-1]`). 화면에서 `parseFloat`·`Number`로 되돌리지 않는다.
 * 예외는 입력 에코인 `distance_nm`·`speed_kn`으로 기능①과 같이 숫자다.
 */

/** `PRD §11.2` 시나리오 3종. */
export type ScenarioType = 'DIRECT' | 'DETOUR' | 'SLOW_STEAMING'

/** 시나리오 1건. */
export interface ScenarioResult {
  scenario_type: ScenarioType
  /** 화면 표시명. `PRD §7.5 scenario_name`. */
  scenario_name: string
  /** **숫자** — 입력 에코 */
  distance_nm: number
  /** **숫자** — 입력 에코 */
  speed_kn: number
  /** Layer 1. `distance_nm / speed_kn`. */
  duration_hours: string
  /** Layer 1 */
  fuel_ton: string
  /** Layer 1 */
  co2_emission_ton: string
  /** Layer 1 */
  attained_cii: string
  /** Layer 1 */
  ratio_to_required: string
  estimated_rating: Rating
  risk_level: RiskLevel
  /** Layer 1. 등급 E는 악화 방향 경계가 없어 `null`이다. */
  next_worse_boundary_margin_ratio: string | null
}

/** 시나리오 비교 요청. */
export interface ScenarioComparisonRequest {
  vessel_id: string
  regulation_year: number
  /** `DIRECT` 시나리오의 거리. 나머지는 `PRD §11.2` 생성 방식을 따른다. */
  base_distance_nm: number
  base_speed_kn: number
  base_fuel_ton: number
  /** `fuel_type` 테이블의 code (예: `HFO`). */
  fuel_type: string
}

/** 시나리오 비교 응답. */
export interface ScenarioComparisonResponse {
  /** `PRD §11.2` 순서 — DIRECT · DETOUR · SLOW_STEAMING */
  scenarios: ScenarioResult[]
  /** Layer 1. 모든 시나리오가 공유한다. */
  required_cii: string
  /** 단위 파생용. 기능①과 같은 규칙(`DESIGN_SYSTEM §4.1`). */
  transport_capacity_basis: CapacityBasis
  ship_type: string
  vessel_display_name: string
  warnings: string[]
  disclaimer: string
}
