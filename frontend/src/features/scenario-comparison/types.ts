import type { CapacityBasis, Rating, RiskLevel, WeatherModel } from '../voyage-cii/types'

/**
 * 기능②(운항 중 시나리오 비교)의 **화면 모델** 타입.
 *
 * ## HTTP 계약이 아니라 화면이 쓰는 모양이다 (`#1619` 정정)
 *
 * 종전 이 머리말은 *「임시 정의다 — `#151` 확정 후 정본에 맞춘다」*로 적혀 있었다.
 * **`#151`은 끝났다.** 지금 이 파일이 맡는 것은 **화면이 쓰는 모양**이고, 서버 payload
 * 와의 차이(`base_distance_nm` → `direct_distance_nm` · `base_speed_kn` →
 * `current_speed_kn`)를 메우는 **변환 책임은 `apiProvider.ts`**에 있다. 그 경계 덕에
 * 화면은 서버 필드명이 바뀌어도 한 자리만 고치면 된다.
 *
 * HTTP 계약의 정본은 `API_SPEC §5.1`이다. 이 파일은 그것을 **다시 적지 않는다** —
 * adapter가 계약을 검사하고(`apiProvider.toScenario`), 어기면 화면까지 올리지 않는다.
 *
 * 필드명은 **`PRD §7.5 VoyageScenario`**를 따른다 — `scenario_type` · `distance_nm` ·
 * `speed_kn` · `duration_hours` · `fuel_ton` · `estimated_rating` · `risk_level`.
 *
 * ## Layer 1 값은 문자열이다
 *
 * `#134`가 기능①에서 확정한 표현 규칙을 그대로 따른다(`API_SPEC §1.7`
 * `[ORACLE-C-1]`). 화면에서 `parseFloat`·`Number`로 되돌리지 않는다.
 * 예외는 입력 에코인 `distance_nm`·`speed_kn`으로 기능①과 같이 숫자다.
 */

/**
 * `PRD §11.2` 시나리오. 뒤의 둘(도착시각 맞춤)은 **선석 가용 시각을 넣었을 때만** 온다 (#2561).
 */
export type ScenarioType = 'DIRECT' | 'DETOUR' | 'SLOW_STEAMING' | 'DIRECT_JIT' | 'DETOUR_JIT'

/**
 * 한 시나리오의 선석 대기 (`API_SPEC §5.1` `scenarios[].berth` · #2561 결정 D8 「다」).
 *
 * **주된 칸(연료·CII·등급)과 따로 받는다** — 주된 칸은 항해만이고, 채택하면 항차 계획에 들어가는
 * 값이다. 대기는 계획에 담기지 않는다(결정 D4).
 */
export interface ScenarioBerth {
  /** Layer 1. 접안까지 = 항해 + 대기. 늦게 닿으면 항해 시간이다. */
  hours_to_berth: string
  /** Layer 1. 선석보다 일찍 닿아 기다리는 시간. 늦게 닿으면 `"0.0000"`. */
  waiting_hours: string
  /** Layer 1. 선석 시각보다 늦게 닿는 시간. 일찍 닿으면 `"0.0000"`. */
  late_hours: string
  /** Layer 1. 묘박 연료가 미입력이고 대기가 있으면 `null`(「계산 못 함」) — 0이 아니다. */
  waiting_fuel_ton: string | null
  /** Layer 1. 대기 연료를 분자에만 더한 CII. 위와 같은 때 `null`. */
  attained_cii_with_waiting: string | null
  estimated_rating_with_waiting: Rating | null
}

/** 도착시각 맞춤 속도가 상한(60kn)을 넘어 **계산하지 않은** 시나리오 (#2561). */
export interface UnreachableScenario {
  scenario_type: ScenarioType
  scenario_name: string
  /** 숫자 — 입력 에코 */
  distance_nm: number
  /** 숫자 — 맞추려면 필요한 속도(0.01kn 올림) */
  required_speed_kn: number
}

/** 시나리오 1건. */
export interface ScenarioResult {
  /**
   * 저장된 시나리오 행의 id — `POST /scenarios/{scenario_id}/adopt`의 경로 값
   * (`API_SPEC §5.1` `[EXT-P0-5]` · `#580`).
   */
  scenario_id: string
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
  /**
   * 이 시나리오에 붙는 경고 코드 (#2561 · `API_SPEC §5.1`). 응답 최상위 `warnings`가 전부를 싣고,
   * 이쪽은 **어느 카드의 경고인가**만 더한다. 옛 응답에는 없어 빈 배열로 읽는다.
   */
  warnings: string[]
  /** 선석 대기 (#2561). 선석 시각을 넣지 않은 비교면 `null`이다. */
  berth: ScenarioBerth | null
}

/** 시나리오 비교 요청. */
export interface ScenarioComparisonRequest {
  vessel_id: string
  regulation_year: number
  /**
   * `DIRECT` 시나리오의 거리. 나머지는 `PRD §11.2` 생성 방식을 따른다.
   *
   * **비울 수 있다**(#1005) — 현재 위치와 목적항 좌표가 모두 있으면 서버가 대권거리로
   * 계산한다(`_resolve_direct_distance()` · `PRD §11.2` 「사용자 입력 또는 좌표 기반 대권거리」).
   */
  base_distance_nm?: number
  base_speed_kn: number
  /**
   * **일일** 연료 소모량 — `API_SPEC §5.1`의 `base_daily_foc_ton`.
   *
   * 총량이 아니라 일일 소모량인 이유: 시나리오마다 소요시간이 달라 **총량으로는
   * 감속 시나리오의 연료를 계산할 수 없다.** demo provider는 API가 없던 시절
   * 총량(`base_fuel_ton`)을 받았으나, API가 생긴 뒤에는 **API가 계약**이다(#139).
   */
  base_daily_foc_ton: number
  /** `fuel_type` 테이블의 code (예: `HFO`). */
  fuel_type: string
  /*
   * --- 선택 입력 (#892) -------------------------------------------------------
   *
   * 전부 **없으면 키를 넣지 않는다.** `API_SPEC §5.1`이 미지정 시의 기본을 서버
   * 규칙으로 규정하므로(`detour = direct x 1.05` · `slow = max(current-1, 1.0)` ·
   * `weather = NONE`), `null`을 실어 보내면 그 규칙과 「명시적 null」이 갈린다.
   */
  /** 미지정 시 서버가 `direct x 1.05` (`API_SPEC §5.1`). */
  detour_distance_nm?: number
  /** VAL-009 `>= 1.0`. 미지정 시 서버가 `max(current_speed - 1, 1.0)`. */
  slow_speed_kn?: number
  /**
   * `PRD §11.3` 현재 위치. **기상 조회의 유일한 입력**이다.
   *
   * 직항 거리를 비우면 목적항 좌표와 함께 **대권거리**의 두 끝이 된다(#1005).
   * 직항 거리가 있으면 서버가 그것을 먼저 쓴다(`_resolve_direct_distance()`).
   */
  current_lat?: number
  current_lon?: number
  /** 목적항 (#1005 · `API_SPEC §5.1`). 샘플 항만에서 골랐을 때만 좌표가 있다. */
  destination_port_name?: string
  destination_lat?: number
  destination_lon?: number
  /**
   * 우회 경유지 (#1300 · `API_SPEC §5.1`). 좌표 둘은 **함께**만 싣는다. 있으면 서버가 우회
   * 거리를 「현재 위치 → 경유지 → 목적항」 대권거리의 합으로 낸다 — `detour_distance_nm`이
   * 있으면 그쪽이 우선이다. 이름은 표기용이다.
   */
  detour_waypoint_name?: string
  detour_waypoint_lat?: number
  detour_waypoint_lon?: number
  /**
   * `API_SPEC §5.1` enum. 미지정 = `NONE`.
   *
   * 기능①의 타입을 **그대로 쓴다** — 유니온을 여기 다시 적으면 서버가 모델을
   * 추가할 때 두 화면 중 하나만 따라간다. `§4.1`과 `§5.1`의 enum이 같은 집합이다.
   */
  weather_model?: WeatherModel
  /**
   * 선체·추진 상태 보정 % (#2561 · `API_SPEC §5.1`). **이번 비교에만** 쓰는 덮어쓰기 값이다 —
   * 없으면 서버가 선박 제원값을, 그것도 없으면 0%를 쓴다. 0은 「보정 없음」이라 싣는다.
   */
  hull_condition_percent?: number
  /**
   * 선석 가용 시각과 그 기준 시각 (#2561 결정 D1 · `API_SPEC §5.1`). **둘이 함께**만 싣는다 —
   * 기준 시각은 화면이 요청을 만드는 순간의 시각이고, 서버는 「지금」을 정하지 않는다
   * (`TECH_SPEC §5.4`). 둘 다 UTC ISO 문자열이다.
   */
  berth_available_at?: string
  berth_reference_at?: string
  /**
   * 묘박 중 일일 연료(t/일 · #2561 결정 D3). **이번 비교에만** 쓰는 덮어쓰기 값이다 — 없으면 서버가
   * 선박 제원값을, 그것도 없으면 대기 연료를 「계산 못 함」으로 둔다.
   */
  anchorage_daily_foc_ton?: number
  /**
   * 이 비교가 **어느 항차를 두고 한 것인가** (`#2217` · `API_SPEC §5.1`). 상단바에 고른 항차다.
   *
   * 계획 단계 항차면 서버가 계산 이력을 그 항차에 붙이고, 채택 없이 끝난 항차의 리포트가 이
   * 비교를 싣는다. 폼의 입력이 아니라 **화면의 문맥**이라 `toRequest`가 아니라 화면이 싣는다.
   */
  voyage_id?: string
}

/** 시나리오 비교 응답. */
export interface ScenarioComparisonResponse {
  /** `PRD §11.2` 순서 — DIRECT · DETOUR · SLOW_STEAMING (· DIRECT_JIT · DETOUR_JIT) */
  scenarios: ScenarioResult[]
  /**
   * 도착시각 맞춤 속도가 60kn을 넘어 계산하지 않은 시나리오 (#2561). 선석 시각이 없거나 모두
   * 계산했으면 빈 배열이다.
   */
  unreachable_scenarios: UnreachableScenario[]
  /** Layer 1. 모든 시나리오가 공유한다. */
  required_cii: string
  /** 단위 파생용. 기능①과 같은 규칙(`DESIGN_SYSTEM §4.1`). */
  transport_capacity_basis: CapacityBasis
  ship_type: string
  /**
   * `API_SPEC §5.1` 응답 최상위의 `warnings`. 화면이 배너로 띄운다.
   *
   * 종전에는 provider가 `[]` 리터럴을 넣어 **배너 조건이 영구 거짓**이었다 (`#821`).
   */
  warnings: string[]
  /** `API_SPEC §5.1` 응답 최상위의 `disclaimer`. **서버 정본을 그대로** 쓴다 (`#821`). */
  disclaimer: string
  /**
   * `API_SPEC §5.1` 응답 최상위의 `calculation_run_id` (#1533). 챗봇이 이 실행의 저장된
   * 결과를 읽는다. 선택 필드 — 가짜 provider·옛 응답에는 없을 수 있다.
   */
  calculation_run_id?: string
  /**
   * 이 비교의 계산 이력이 **붙은** 항차 (`API_SPEC §5.1` `data.voyage_id` · `#2217`).
   * 붙지 않았으면 `null`이다 — 요청이 항차를 밝히지 않았거나, 밝혔어도 그 항차가 계획
   * 단계가 아니었다. 화면은 이 값으로 「어느 항차의 비교로 남았는가」를 알리고, 채택 대상을
   * 그 항차로 좁힌다(`§5.2`). 선택 필드 — 가짜 provider에는 없을 수 있고 `null`과 같게 읽는다.
   */
  voyage_id?: string | null
  /**
   * 보정에 쓴 기상 스냅샷을 **받은 시각** (`API_SPEC §5.1` `data.weather.fetched_at` · `#2135`).
   * 기상 보정을 하지 않았으면 `null`이다. 화면은 이 값으로 「기상 기준 시각」 한 줄을 내고,
   * 없으면 「기상 보정 없이 계산했습니다」를 낸다. 선택 필드 — 가짜 provider에는 없을 수 있고
   * `null`과 같게 읽는다.
   */
  weather_fetched_at?: string | null
  /**
   * 세 시나리오에 공통으로 건 계산 조건 (`API_SPEC §5.1` `data.conditions` · #2561). 선택
   * 필드 — 가짜 provider·옛 응답에는 없을 수 있고, 그때 화면은 조건 줄을 내지 않는다.
   */
  conditions?: ScenarioConditions | null
}

/**
 * 선체·추진 상태 보정의 값과 출처 (#2561).
 *
 * 출처를 따로 받는 것은 **「미입력」과 「0%를 넣음」이 다른 말**이기 때문이다 — 계산은
 * 같아도 앞은 「모른다」이고 뒤는 「깨끗하다고 확인했다」이다.
 */
export interface ScenarioConditions {
  /** `null`이면 미입력(0%로 계산). */
  hull_condition_percent: number | null
  hull_condition_source: 'REQUEST' | 'VESSEL' | 'NOT_SET'
  /** 선석 가용 시각(UTC ISO · #2561). 선석 시각을 넣지 않았으면 `null`. */
  berth_available_at: string | null
  /** Layer 1. 선석까지 남은 시간. 선석 시각이 없으면 `null`. */
  hours_until_berth: string | null
  /** 대기 연료에 쓴 묘박 중 일일 연료(t/일). 미입력이면 `null`. */
  anchorage_daily_foc_ton: number | null
  anchorage_daily_foc_source: 'REQUEST' | 'VESSEL' | 'NOT_SET'
}

/**
 * 시나리오 채택 결과 — `POST /scenarios/{id}/adopt` (`API_SPEC §5.2` · `#580`).
 *
 * `invalidated_calculation_runs`는 **받는다** (`#1077`). 종전에는 `#817`
 * (`calculation_run.voyage_id`가 늘 `NULL`)이 닫히기 전에는 이 수가 항상 `0`이고 참값이
 * 아니라 받지 않았는데(2026-09-08 착수 판정), **`#817`이 2026-09-11에 닫혔다** —
 * 항차를 밝힌 계산이 그 항차에 귀속되므로 이제 참값이다.
 *
 * ⚠️ **선택 필드로 둔다.** 서버가 싣지 않은 응답(`0`이 아니라 **필드 자체가 없는** 경우)과
 * `0`은 뜻이 다르다 — 앞은 「알 수 없다」이고 뒤는 「새로 표시된 계산이 없다」이다. 둘을
 * 같은 모양으로 그리면 사용자는 가장 나쁜 해석을 고른다.
 */
export interface ScenarioAdoptResult {
  voyage_id: string
  adopted_scenario_type: ScenarioType
  /** 서버가 덮어쓴 항차 필드 — `planned_distance_nm` 등 */
  updated_fields: string[]
  /**
   * 이번 채택으로 **새로** 재계산 필요 표시가 붙은 그 항차의 계산 결과 수 (`API_SPEC §5.2`).
   *
   * `0`은 「계산 이력이 없다」와 「이미 전부 표시돼 있다」 **둘 다**일 수 있다(정본 명시).
   * 그래서 `0`을 「무효화된 것이 없다」로 단정해 적지 않는다. 서버가 필드를 싣지 않았으면
   * `undefined`이며, 그때는 **수를 말하지 않는다.**
   */
  invalidated_calculation_runs?: number
}
