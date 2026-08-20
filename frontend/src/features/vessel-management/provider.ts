import type { Vessel } from '../vessel-registration/types'

/**
 * 선박 관리(목록·수정·삭제)의 데이터 경계 (#510).
 *
 * ## `vessel-registration`과 나눈 이유
 *
 * 등록은 **온보딩 흐름**(`UIFLOW 1-1 → 1-2 → 1-3`)이고 관리는 **운영 중 조작**이다.
 * 진입 경로도 화면도 다르다. 한 provider에 묶으면 등록 화면이 쓰지 않는 `remove()`를
 * 갖고, 관리 화면이 쓰지 않는 온보딩 전용 규칙을 물려받는다.
 *
 * 대신 **타입은 공유한다** — `Vessel`은 같은 서버 객체(`API_SPEC §2.1`)이며, 여기서
 * 다시 정의하면 서버가 필드를 늘릴 때 두 곳이 갈린다.
 *
 * ## 목록은 읽기, 수정·삭제는 쓰기
 *
 * 셋을 한 인터페이스에 두되 **데모 모드에서 갈라진다** — 목록은 보여 줄 수 있으나
 * 수정·삭제는 서버에 저장되는 조작이라 흉내 낼 수 없다(`providerSelection.ts`).
 */

/** `PATCH /api/v1/vessels/{id}` 요청 본문 (`API_SPEC §2.4`). */
export interface VesselUpdateRequest {
  name?: string
  ship_type?: string
  gross_tonnage?: number | null
  deadweight?: number | null
  default_fuel_type?: string | null
  reference_speed_kn?: number | null
  reference_daily_foc_ton?: number | null
}

/**
 * 목록 조회 결과.
 *
 * `meta.next_cursor`·`has_more`를 함께 돌려준다 — `GET /vessels`가 커서 페이지네이션을
 * 쓰는데(`routes/vessels.py:54`), 화면이 그것을 모르면 **21척째부터 조용히 사라진다.**
 */
export interface VesselPage {
  vessels: Vessel[]
  nextCursor: string | null
  hasMore: boolean
}

export interface VesselManagementProvider {
  list(options?: { cursor?: string; search?: string }): Promise<VesselPage>
  update(vesselId: string, patch: VesselUpdateRequest): Promise<Vessel>
  remove(vesselId: string): Promise<void>
}

/**
 * 관리 조작 실패의 종류.
 *
 * `vessel-registration`의 4종과 겹치지 않는 것이 둘 있다.
 *
 * | 코드 | 사용자가 할 수 있는 것 |
 * |---|---|
 * | `VALIDATION_ERROR` | 입력을 고친다 |
 * | `NOT_FOUND` | 없다. 이미 삭제됐거나 다른 사람이 지웠다 — 목록을 다시 읽는다 |
 * | `CONFLICT` | 참조가 걸려 있다 |
 * | `MANAGEMENT_ERROR` | 없다. 다시 시도하거나 운영자에게 문의한다 |
 */
export type VesselManagementErrorCode =
  | 'VALIDATION_ERROR'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'MANAGEMENT_ERROR'

/**
 * 관리 조작 실패.
 *
 * `field`는 등록과 같은 **요청 본문 기준 경로**다(`api/error_handlers.py _field_path()`).
 * 수정 폼이 화면 검증 결과와 같은 맵에 병합할 수 있어야 한다.
 */
export class VesselManagementError extends Error {
  readonly code: VesselManagementErrorCode
  readonly field?: string

  constructor(
    code: VesselManagementErrorCode,
    message: string,
    field?: string,
    options?: { cause?: unknown },
  ) {
    super(message, options)
    this.name = 'VesselManagementError'
    this.code = code
    this.field = field
  }
}
