/**
 * 선박 등록(`POST /api/v1/vessels`)의 요청·응답 타입 (#441).
 *
 * ## 값이 숫자다 — Layer 1이 아니다
 *
 * `gross_tonnage`·`deadweight`·`reference_speed_kn`은 **계산 입력**이고 결정론 산출값이
 * 아니다. `API_SPEC §1.7`의 Layer 1 문자열 직렬화는 계산 **결과**에만 적용된다
 * (`services/vessel.py _number()` 주석이 같은 근거로 `float`을 쓴다).
 *
 * 기능①·③ 응답 타입에서 값이 전부 문자열인 것과 **반대 방향**이므로 섞지 않는다.
 *
 * ## 선택 입력을 `undefined`로 둔다
 *
 * `API_SPEC §2.3`상 필수는 `imo_number`·`name`·`ship_type` 셋뿐이다. 나머지는
 * `VesselCreateRequest`에서 전부 `None` 기본값이며, 이것이 `PRD §20 O-11`
 * 「IMO 조회 실패 시 수동 입력 허용」이 열어 둔 경로다 — **제원 없이도 등록된다.**
 */

/** `POST /api/v1/vessels` 요청 본문 (`API_SPEC §2.3`). */
export interface VesselCreateRequest {
  /** VAL-003 — 7자리 숫자 문자열. 숫자 타입이 아니다(선행 0이 사라진다). */
  imo_number: string
  /** VAL-001 — 1~100자. */
  name: string
  /** VAL-004 — 파라미터 테이블에 행이 있는 선종. */
  ship_type: string
  gross_tonnage?: number
  deadweight?: number
  default_fuel_type?: string
  reference_speed_kn?: number
  reference_daily_foc_ton?: number
}

/**
 * 등록된 선박 객체 (`API_SPEC §2.1`).
 *
 * 응답 전체를 그대로 담는다 — 화면이 쓰는 필드만 뽑으면 「무엇이 저장됐는지」를
 * 사용자에게 되보여 줄 수 없다. 등록은 되돌리기 어려운 조작이므로 결과 확인이 중요하다.
 */
export interface Vessel {
  id: string
  imo_number: string
  name: string
  ship_type: string
  /** 제원 미입력이면 `null`. `DB_SCHEMA §2.1`상 nullable이다. */
  gross_tonnage: number | null
  deadweight: number | null
  default_fuel_type: string | null
  reference_speed_kn: number | null
  reference_daily_foc_ton: number | null
  /**
   * CII 적용 대상 추정 — **서버가 정한다**(`API_SPEC §2.3`: GT ≥ 5,000).
   *
   * 화면이 GT로 다시 판정하지 않는다. 기준이 바뀌면 두 곳이 갈리고, 갈린 쪽이
   * 화면이면 사용자가 잘못된 안내를 받는다.
   */
  is_cii_applicable_hint: boolean
  underway_state: string | null
  detail_status: string | null
  current_lat: number | null
  current_lon: number | null
  position_updated_at: string | null
  created_at: string | null
  updated_at: string | null
}
