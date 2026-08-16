import type { ScenarioComparisonRequest, ScenarioComparisonResponse } from './types'

/**
 * 기능② 시나리오 비교의 데이터 경계.
 *
 * **화면은 데이터 출처를 알지 않는다.** 8/8 데모는 `demoScenarioProvider`를 쓰고,
 * 기능② API(`#57`)가 준비되면 `apiScenarioProvider`로 구현체만 교체한다(`#139`).
 * 그때 화면 코드는 바뀌지 않는다 — `#134`가 기능①에서 세운 구조와 같다.
 *
 * **응답을 시나리오 배열로 설계한 것이 그 교체의 조건이다.** `#57` 응답 구조와 맞아
 * 화면이 배열을 반복 렌더링하기만 하면 된다.
 */
export interface ScenarioComparisonProvider {
  compare(request: ScenarioComparisonRequest): Promise<ScenarioComparisonResponse>
}

/**
 * provider 오류 코드.
 *
 * 기능①의 `VoyageCiiErrorCode`와 겹치는 항목이 있으나 **같은 타입을 재사용하지
 * 않는다.** 두 API의 오류 집합이 앞으로 갈릴 수 있고, 한쪽이 코드를 추가할 때
 * 다른 쪽 화면이 처리하지 않는 코드를 타입상 처리해야 하는 상태가 된다.
 */
export type ScenarioComparisonErrorCode =
  /** 요청 값이 검증 규칙을 위반 (`API_SPEC §11` VAL-002 · VAL-006 · VAL-009) */
  | 'VALIDATION_ERROR'
  /** demo provider의 고정표에 없는 선박 */
  | 'UNSUPPORTED_VESSEL'
  /** 고정표에 없는 규제연도 */
  | 'UNSUPPORTED_YEAR'
  /** 알 수 없는 연료 코드 */
  | 'UNKNOWN_FUEL_TYPE'
  /** 입력 검증은 통과했으나 계산 결과가 유효하지 않다 */
  | 'CALCULATION_ERROR'

export class ScenarioComparisonError extends Error {
  readonly code: ScenarioComparisonErrorCode
  /** 요청 본문 기준 필드 경로. 없으면 요청 전체 문제. */
  readonly field?: string

  /**
   * ``options.cause``는 **원인 예외를 잃지 않기 위해** 받는다 (#139).
   *
   * `apiProvider`가 네트워크 실패를 사용자 문구로 바꿔 던지는데, 원본을 버리면
   * 개발자 도구에서 무엇이 끊겼는지 알 수 없다(기능①의 `VoyageCiiError`와 같은 이유).
   */
  constructor(
    code: ScenarioComparisonErrorCode,
    message: string,
    field?: string,
    options?: { cause?: unknown },
  ) {
    super(message, options)
    this.name = 'ScenarioComparisonError'
    this.code = code
    this.field = field
  }
}
