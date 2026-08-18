import type { Vessel, VesselCreateRequest } from './types'

/**
 * 선박 등록의 데이터 경계 (#441).
 *
 * 파일을 `types.ts`와 나눈 것은 기능①(`voyage-cii/provider.ts`)과 같은 구성이다 —
 * `types.ts`는 계약의 **모양**, 이 파일은 화면이 의존하는 **경계와 실패**다.
 */
export interface VesselRegistrationProvider {
  register(request: VesselCreateRequest): Promise<Vessel>
}

/**
 * 등록 실패의 종류.
 *
 * 서버 오류 코드(`API_SPEC §1.4`)를 그대로 쓰지 않는다. 화면이 갈라야 하는 것은
 * **사용자가 무엇을 할 수 있는가**이고, 그 기준으로는 4가지면 된다.
 *
 * | 코드 | 사용자가 할 수 있는 것 |
 * |---|---|
 * | `VALIDATION_ERROR` | 입력을 고친다 |
 * | `CONFLICT` | 이미 등록된 IMO다 — 다른 배이거나, 그 배를 찾아 들어간다 |
 * | `DEMO_UNAVAILABLE` | 없다. 데모 모드에서는 등록 자체가 불가능하다 |
 * | `REGISTRATION_ERROR` | 없다. 다시 시도하거나 운영자에게 문의한다 |
 */
export type VesselRegistrationErrorCode =
  | 'VALIDATION_ERROR'
  | 'CONFLICT'
  | 'DEMO_UNAVAILABLE'
  | 'REGISTRATION_ERROR'

/**
 * 등록 실패.
 *
 * `field`는 **요청 본문 기준 경로**(`imo_number`·`deadweight` …)다. 서버가
 * `details[0].field`를 그 형태로 내려주므로(`api/error_handlers.py _field_path()`)
 * 화면 검증 결과와 같은 맵에 병합할 수 있다.
 */
export class VesselRegistrationError extends Error {
  readonly code: VesselRegistrationErrorCode
  readonly field?: string

  constructor(
    code: VesselRegistrationErrorCode,
    message: string,
    field?: string,
    options?: { cause?: unknown },
  ) {
    super(message, options)
    this.name = 'VesselRegistrationError'
    this.code = code
    this.field = field
  }
}
