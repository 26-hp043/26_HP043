import type { VoyageCiiRequest, VoyageCiiResponse } from './types'

/**
 * 기능① 계산의 데이터 경계.
 *
 * **화면은 데이터 출처를 알지 않는다.** 8/8 데모는 `demoProvider`를 쓰고,
 * 기능① API(#55)가 준비되면 `apiProvider`로 구현체만 교체한다(#138).
 * 그때 화면 코드는 바뀌지 않는다.
 */
export interface VoyageCiiProvider {
  estimate(request: VoyageCiiRequest): Promise<VoyageCiiResponse>
}

/**
 * provider 오류 코드.
 *
 * `enum`이 아니라 문자열 리터럴 유니온을 쓴다 — `API_SPEC §1.3.2`의 오류 응답이
 * 문자열 코드를 내려주므로 실제 API provider가 같은 타입을 그대로 쓸 수 있다.
 */
export type VoyageCiiErrorCode =
  /** 요청 값이 검증 규칙을 위반 (`API_SPEC §11` VAL-002 · VAL-006 · VAL-009) */
  | 'VALIDATION_ERROR'
  /** demo provider의 고정표에 없는 선박 */
  | 'UNSUPPORTED_VESSEL'
  /** 고정표에 없는 규제연도 */
  | 'UNSUPPORTED_YEAR'
  /** 알 수 없는 연료 코드 */
  | 'UNKNOWN_FUEL_TYPE'
  /**
   * 입력 검증은 통과했으나 계산 결과가 유효하지 않다 (`NaN` · `Infinity` · 0 이하).
   * `#37` 엔진의 출력 가드 `[ORACLE-MISS-2]`와 같은 성격이다.
   */
  | 'CALCULATION_ERROR'

/**
 * provider가 던지는 오류.
 *
 * `field`는 입력 폼의 해당 입력창에 메시지를 붙이기 위한 것이다(#135).
 * 실제 API 연결 시에는 서버가 내려주는 `field`·`field_label`로 대체된다(#138).
 */
export class VoyageCiiError extends Error {
  readonly code: VoyageCiiErrorCode
  /** 요청 본문 기준 필드 경로 (예: `fuel_uses[0].fuel_ton`). 없으면 요청 전체 문제. */
  readonly field?: string

  /**
   * `options.cause`는 **원인 예외를 잃지 않기 위해** 받는다(#138).
   *
   * `apiProvider`가 네트워크 실패(`TypeError: Failed to fetch`)를 사용자 문구로 바꿔
   * 던지는데, 원본을 버리면 개발자 도구에서 무엇이 끊겼는지 알 수 없다. 사용자에게는
   * `message`만 보이고 `cause`는 콘솔에만 남는다.
   */
  constructor(
    code: VoyageCiiErrorCode,
    message: string,
    field?: string,
    options?: { cause?: unknown },
  ) {
    super(message, options)
    this.name = 'VoyageCiiError'
    this.code = code
    this.field = field
  }
}
