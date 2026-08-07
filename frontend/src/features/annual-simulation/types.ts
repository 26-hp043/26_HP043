import type { CapacityBasis, Rating, RiskLevel } from '../voyage-cii/types'

/**
 * 기능③(연간 CII 시뮬레이션)의 응답 타입.
 *
 * ## ⚠️ 임시 정의다 — `#63`·`#64` 확정 후 정본에 맞춘다
 *
 * 연간 시뮬레이션 엔진(`#63`)과 API(`#64`)는 `2026.10` 마일스톤이고, `#64`는
 * **동기/비동기 처리 방식조차 미결**이다. 이 타입은 그 결정을 **선점하지 않는다** —
 * 화면이 목업을 그릴 수 있는 최소 형태만 정의하고, provider 인터페이스만 `#134`와
 * 같은 모양으로 맞춰 둔다.
 *
 * ## 확률 필드를 두지 않는다
 *
 * `DESIGN_SYSTEM §2.5 (a)`의 확률 임계값(20% / 40%)이 **초안값**이고 `P(D∪E)`의
 * **계산 정의 자체가 `PRD`에 없다**(`#170` 확인 항목 ⑶ 잔존). 필드를 만들어 두면
 * 화면에 붙게 되고, 그 순간 미결에 걸린다.
 *
 * ## Layer 1 값은 문자열이다
 *
 * `#134`가 확정한 표현 규칙을 따른다(`API_SPEC §1.7` `[ORACLE-C-1]`).
 * 화면에서 `parseFloat`·`Number`로 되돌리지 않는다.
 */

/** 월별 집계 1건. */
export interface MonthlySummary {
  /** `YYYY-MM` */
  month: string
  /** **숫자** — 집계 대상 항차 수 */
  voyage_count: number
  /** **숫자** — 입력 에코 성격 */
  distance_nm: number
  /** Layer 1 */
  fuel_ton: string
  /** Layer 1 */
  co2_emission_ton: string
  /** Layer 1. 그 달만의 CII. */
  attained_cii: string
}

/** 연간 시뮬레이션 결과. */
export interface AnnualSimulationResult {
  vessel_display_name: string
  ship_type: string
  regulation_year: number
  transport_capacity_basis: CapacityBasis
  /** Layer 1 */
  required_cii: string
  /** Layer 1. 집계 구간 전체의 CII. */
  attained_cii: string
  /** Layer 1 */
  ratio_to_required: string
  estimated_rating: Rating
  risk_level: RiskLevel
  /** Layer 1. 등급 E는 `null`. */
  next_worse_boundary_margin_ratio: string | null
  /** **숫자** */
  total_distance_nm: number
  /** Layer 1 */
  total_fuel_ton: string
  /** Layer 1 */
  total_co2_emission_ton: string
  months: MonthlySummary[]
  warnings: string[]
  disclaimer: string
  /**
   * **이 결과가 실제 계산이 아니라 예시 데이터임을 나타낸다.**
   *
   * 필드로 두는 이유는 화면이 「예시 데이터」 배지를 **응답에서 판단**하게 하기
   * 위해서다. 화면에 배지를 상수로 박아 두면 `#63`·`#64` 연결 후에도 남는다.
   */
  is_sample_data: boolean
}
