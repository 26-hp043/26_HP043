/**
 * 기능①(항차 CII 추정)의 요청·응답 타입.
 *
 * **필드명과 JSON 타입은 `API_SPEC.md` §4.1 응답 타입 표를 그대로 옮겼다.**
 * 확정 경위는 이슈 #132 코멘트에 있다.
 *
 * ⚠️ **Layer 1 결정론 수치는 JSON 문자열이다**(`API_SPEC §1.7` `[ORACLE-C-1]`).
 * 문자열로 직렬화해 JSON float 파싱에 의한 정밀도 손실을 막는다.
 * 화면에서 `parseFloat()`·`Number()`로 되돌리지 않고 `formatDecimalString()`을 통해
 * 표시 형식만 바꾼다(#134 표시 규칙).
 *
 * 응답 전체가 문자열은 아니다 — `distance_nm`은 입력 에코라 숫자,
 * `model_version`은 `decimal_precision`만 숫자인 혼합 타입이다.
 */

/** 등급. `PRD §3.3.6` 판정 결과. */
export type Rating = 'A' | 'B' | 'C' | 'D' | 'E'

/** 결정론 화면 위험도. `PRD §9.4.1`. */
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

/** transport capacity의 기준 축. `PRD §3.3.3`. */
export type CapacityBasis = 'DWT' | 'GT'

/**
 * 기상 모델. `API_SPEC §4.1` enum.
 * 8/8 UI는 이 값을 수집하지 않고 요청에서도 생략한다(서버 기본값 `NONE`).
 */
export type WeatherModel = 'NONE' | 'SIMPLE_RULE' | 'TOWNSIN_KWON_ALPHA'

/** 연료 사용 1건. 화면의 단일 연료 입력을 길이 1의 배열로 매핑한다(#135). */
export interface FuelUseInput {
  /** `fuel_type` 테이블의 code (예: `HFO`). `fuel_type_id`가 아니다. */
  fuel_type: string
  fuel_ton: number
}

/** `POST /api/v1/calculations/voyage-cii` 요청. */
export interface VoyageCiiRequest {
  vessel_id: string
  regulation_year: number
  distance_nm: number
  /** 평균 예정 속력. **Layer 1 계산의 피연산자가 아니다** — 아래 주석 참조. */
  speed_kn: number
  /** 최소 1개. 동일 `fuel_type`이 여러 행이면 합산한다. */
  fuel_uses: FuelUseInput[]
  weather_model?: WeatherModel
  /**
   * 이 계산이 **어느 항차의 것인가** (#817 · `API_SPEC §4.1`). 「계획 저장」이 만든 항차로
   * 계산을 한 번 더 기록할 때만 싣는다 — 그래야 그 항차 계획이 바뀔 때 재계산 필요로 표시된다.
   */
  voyage_id?: string
}

/**
 * `speed_kn`은 계산에 쓰이지 않는다.
 *
 * `attained_CII = M / W`이고 `W = transport_capacity × distance_nm`이라 속력이 들어갈
 * 자리가 구조적으로 없다. 사용자가 연료량을 직접 입력하기 때문이며, 누락이 아니라
 * 기능①의 설계 결과다(`PRD §10.3`).
 *
 * 따라서 **같은 선박·연도·거리·연료 사용량에서 속력만 바꾸면 결과가 변하지 않는다.**
 * 속력 기반 연료 추정은 `#75`(cubic speed model) 소관이며 8/8 범위 밖이다.
 */

/** 연료 종류별 CO₂ 산정 내역. 연료 종류당 한 행으로 정규화한다. */
export interface FuelCfDetail {
  fuel_type: string
  /** Layer 1 */
  cf: string
  /** Layer 1. 동일 `fuel_type` 입력 행의 합. */
  fuel_ton: string
}

/** 계산 근거. */
export interface CalculationBasis {
  ship_type: string
  /** Layer 1 */
  z_factor_percent: string
  fuel_cf_details: FuelCfDetail[]
  /** Layer 1 */
  a_decimal: string
  /** Layer 1 */
  c: string
}

/** 응답 `data`. */
export interface VoyageCiiData {
  /** Layer 1 */
  attained_cii: string
  /** Layer 1 */
  required_cii: string
  /** Layer 1 */
  ratio_to_required: string
  estimated_rating: Rating
  /**
   * Layer 1. 다음 악화 등급 경계까지의 여유.
   * 등급 E는 더 나쁜 등급이 없어 `null`이다.
   */
  /** 등급 경계 CII 4종 — 서버가 Layer 1 컨텍스트 안에서 낸 값 (#1371 · API_SPEC §4.1). */
  rating_boundary_cii: {
    superior_boundary: string
    lower_boundary: string
    upper_boundary: string
    inferior_boundary: string
  }
  next_worse_boundary_margin: string | null
  /** Layer 1. 위 값 ÷ `required_cii`. 등급 E는 `null`. */
  next_worse_boundary_margin_ratio: string | null
  /** Layer 1 */
  co2_emission_ton: string
  /** Layer 1. 입력 연료량 전체의 합. */
  fuel_consumption_ton: string
  /** **숫자** — 입력 에코 */
  distance_nm: number
  risk_level: RiskLevel
  /** Layer 1 */
  transport_capacity: string
  transport_capacity_basis: CapacityBasis
  /** Layer 1 */
  reference_capacity: string
  /** **enum이 아니다** — 파라미터 테이블 값 그대로 (`DWT` · `GT` · `fixed 279000` 등) */
  reference_capacity_rule: string
  /**
   * 「연간 반영 시 변화」 — `PRD §10.3` ⑨ · `§10.4` 출력 행 (`#1338`).
   *
   * ⚠️ **항차 CII와 다른 질문에 답한다.** 항차 CII는 「이 항차 하나의 강도」이고
   * 이 블록은 「선박의 연말 값이 이 항차 때문에 어디로 가나」다 —
   * **두 값이 반대 방향을 가리키는 것이 정상**이다.
   *
   * 기초 자료(확정 실적·잔여 계획)가 없으면 `null`이다. 「0과 비교한 숫자」를
   * 지어내지 않는다.
   */
  annual_impact: AnnualImpact | null
  calculation_basis: CalculationBasis
}

/** `data.annual_impact` (`API_SPEC §4.1` · `#1338`). */
export interface AnnualImpact {
  before: AnnualImpactSide
  after: AnnualImpactSide
  rating_changed: boolean
}

/**
 * ⚠️ **`export`하지 않는다.** 이 이름을 밖에서 부르는 곳이 없고,
 * `moduleBoundary.test.ts`가 **미참조 export를 죽은 코드로 잡는다**(`#1351`).
 * `AnnualImpact`의 구조로만 쓰이므로 구조적 타이핑으로 충분하다.
 */
interface AnnualImpactSide {
  /** Layer 1 — `attained_cii`와 같은 6자리 문자열 */
  attained_cii: string
  rating: Rating
}

/** 사용된 파라미터. 하위 수치는 전부 문자열. */
export interface ParametersUsed {
  regulation_year: { year: string; z_factor_percent: string }
  fuel_types: Array<{ code: string; cf: string }>
  reference_line: {
    ship_type: string
    reference_capacity_rule: string
    a_decimal: string
    c: string
  }
  rating_boundary: { d1: string; d2: string; d3: string; d4: string }
  parameter_source_version: string
}

/** 엔진 버전 정보. **혼합 타입** — `decimal_precision`만 숫자다. */
export interface ModelVersion {
  engine: string
  decimal_precision: number
  decimal_rounding: string
  rng_algorithm: string
  numpy_version: string
  python_version: string
}

/** 응답 메타. */
export interface ResponseMeta {
  request_id: string
  /** ISO 8601 */
  timestamp: string
  duration_ms: number
}

/** `POST /api/v1/calculations/voyage-cii` 응답 (200). */
export interface VoyageCiiResponse {
  data: VoyageCiiData
  parameters_used: ParametersUsed
  calculation_run_id: string
  model_version: ModelVersion
  /** `sha256:…` */
  input_hash: string
  /** `sha256:…` */
  parameter_hash: string
  warnings: string[]
  disclaimer: string
  meta: ResponseMeta
}
