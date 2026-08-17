import type { Vessel } from './types'

/**
 * 등록 결과 표시 규칙 (#441).
 *
 * 컴포넌트에서 분리한 이유는 `formRules.ts`와 같다 — **분기가 테스트 가능해야 한다.**
 * 저장소에 `@testing-library/react`·`jsdom`이 없어 컴포넌트 안의 삼항 연산자는
 * 아무도 검사하지 않는다.
 */

/**
 * `is_cii_applicable_hint`를 사용자 언어로 옮긴다.
 *
 * **「미해당」의 두 원인을 구분한다.** 서버는 GT 기준으로 판정하는데(`API_SPEC §2.3`),
 * GT가 비어 있어도 `false`가 나온다. 두 경우에 같은 말을 하면 **총톤수를 넣지 않은
 * 사용자가 「이 배는 규제 대상이 아니다」로 읽는다.**
 *
 * 임계값(GT 5,000)을 화면에 적지 않는다 — 판정은 서버 소관이고, 숫자를 여기 박으면
 * 기준이 바뀔 때 화면만 낡는다. 화면이 GT로 **다시 판정하지도 않는다**.
 */
export function applicabilityHint(vessel: Vessel): string {
  if (vessel.is_cii_applicable_hint) {
    return '이제 항차를 등록하면 이 선박의 CII가 집계됩니다.'
  }
  if (vessel.gross_tonnage === null) {
    return '총톤수(GT)가 비어 있어 CII 적용 대상이 아닌 것으로 판정됐습니다. 총톤수를 채우면 다시 판정됩니다.'
  }
  return 'CII 적용 대상이 아닌 것으로 판정됐습니다. 총톤수가 맞는지 확인해 주세요.'
}

/**
 * 제원 값의 표시. 없으면 **「미입력」으로 적는다.**
 *
 * 빈 칸으로 두면 「입력했는데 안 보인다」와 구분되지 않는다 — `#449`가 경고를 값으로
 * 만든 것과 같은 원칙이다. 없다는 사실도 정보다.
 */
export function numberOrMissing(value: number | null): string {
  if (value === null) return '미입력'
  return value.toLocaleString('ko-KR')
}
