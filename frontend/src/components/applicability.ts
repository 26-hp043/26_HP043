/**
 * CII 적용 대상 판정을 화면 언어로 옮기는 단일 규칙 (#653).
 *
 * ## 왜 한 곳인가
 *
 * 종전에는 이 규칙이 `vessel-registration/resultRules.ts` 안에만 있었고, 그 화면은
 * **등록 직후 한 번만 지나간다.** 이후 목록·상세·대시보드 어디에서도 그 선박이
 * 규제 대상인지 알 수 없었다 — 계산은 정상적으로 도는데 그 값이 규제상 무의미할 수
 * 있다는 사실을 화면이 말하지 않았다.
 *
 * ## 화면이 다시 판정하지 않는다
 *
 * 임계값(GT 5,000)을 이 파일에 적지 않는다. 판정은 서버 소관이고(`API_SPEC §2.3`),
 * 숫자를 화면에 박으면 규제 하한이 바뀔 때 화면만 낡는다. 화면은 서버가 내린
 * `is_cii_applicable_hint`를 **그대로 받아** 「미해당의 원인」만 가른다.
 */

/**
 * 판정 3상태. 서버 `services/applicability.py`의 상태명과 같은 이름을 쓴다 —
 * 다르게 부르면 로그와 화면을 대조할 때 매번 번역해야 한다.
 */
export type ApplicabilityState = 'APPLICABLE' | 'NOT_APPLICABLE' | 'UNKNOWN'

export interface ApplicabilityInput {
  /** 서버 판정 (`API_SPEC §2.3`). 화면이 만들지 않는다. */
  isCiiApplicableHint: boolean
  /**
   * 총톤수. **판정에 쓰지 않고 「미해당의 원인」을 가르는 데만 쓴다.**
   * 응답에 따라 number(`§2.1`)이거나 문자열이라 둘 다 받는다.
   */
  grossTonnage: number | string | null
}

/**
 * 「미해당」의 두 원인을 가른다.
 *
 * 서버는 GT 기준으로 판정하는데, **GT가 비어 있어도 `false`가 나온다.** 두 경우에
 * 같은 말을 하면 총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다.
 * 데모 시드의 실선 2척(`STAR SKIPPER` · `DONGJIN ENDURANCE`)이 정확히 후자다.
 */
export function applicabilityState({
  isCiiApplicableHint,
  grossTonnage,
}: ApplicabilityInput): ApplicabilityState {
  if (isCiiApplicableHint) return 'APPLICABLE'
  if (grossTonnage === null) return 'UNKNOWN'
  return 'NOT_APPLICABLE'
}

/**
 * 배지에 적는 짧은 라벨. 전체 문구는 {@link APPLICABILITY_FULL_TEXT}가 갖는다.
 *
 * 목록에서 스무 척을 훑을 때 한 줄이 두 줄로 접히면 표가 무너진다 —
 * `RegulatoryFlag`가 같은 이유로 짧은 라벨과 전체 문구를 나눠 두었다.
 */
export const APPLICABILITY_SHORT_LABEL: Readonly<Record<ApplicabilityState, string>> = {
  APPLICABLE: '',
  NOT_APPLICABLE: '규제 대상 아님',
  UNKNOWN: 'GT 미입력',
}

/**
 * 전체 문구 — `title`·`aria-label`로 나간다.
 *
 * `NOT_APPLICABLE`은 **`PRD §6.3`「공식 적용 대상 아님」의 원문 그대로**다. 문구를
 * 새로 쓰지 않는다(`AGENTS §3`). `UNKNOWN`은 `API_SPEC §1.6`
 * `CII_APPLICABILITY_UNKNOWN` 행의 사용자 메시지를 옮긴 것이다.
 */
export const APPLICABILITY_FULL_TEXT: Readonly<Record<ApplicabilityState, string>> = {
  APPLICABLE: '',
  NOT_APPLICABLE: '입력 선박은 공식 CII 적용 대상이 아닐 수 있습니다. 내부 분석용으로만 사용하세요.',
  UNKNOWN:
    '총톤수(GT)가 없어 공식 CII 적용 대상 여부를 판정할 수 없습니다. 선박 제원에 총톤수를 입력해 주세요.',
}
