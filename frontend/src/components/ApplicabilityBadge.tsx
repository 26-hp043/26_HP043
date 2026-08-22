import './ApplicabilityBadge.css'
import {
  APPLICABILITY_FULL_TEXT,
  APPLICABILITY_SHORT_LABEL,
  applicabilityState,
  type ApplicabilityInput,
} from './applicability'

/**
 * CII 적용 대상 배지 — `DESIGN_SYSTEM §8` (`#653`).
 *
 * ## 왜 필요한가
 *
 * `PRD §3.1`은 5,000 GT 미만 선박도 **계산 자체는 허용**하고, `PRD.md:161`이
 * *「다만 화면에는 「공식 CII 적용 대상이 아닐 수 있음」을 표시해야 한다」*고 요구한다.
 * 그 표시가 등록 결과 화면 한 곳에만 있었다 — 등급과 값은 어디서나 보이는데
 * **그 값이 규제상 무의미할 수 있다는 사실만 보이지 않았다.**
 *
 * ## 적용 대상이면 아무것도 그리지 않는다
 *
 * 정상 상태에 배지를 붙이면 목록 스무 줄이 전부 배지로 덮여 **정작 예외인 두 척이
 * 묻힌다.** `RegulatoryFlags`가 빈 배열에서 `null`을 돌려주는 것과 같은 판단이다.
 */
export function ApplicabilityBadge({
  isCiiApplicableHint,
  grossTonnage,
  vesselName,
}: ApplicabilityInput & {
  /** 어느 선박의 배지인지 — 목록에서 읽힐 때 대상이 없으면 뜻이 없다. */
  vesselName?: string
}) {
  const state = applicabilityState({ isCiiApplicableHint, grossTonnage })
  if (state === 'APPLICABLE') return null

  const full = APPLICABILITY_FULL_TEXT[state]
  const label = vesselName ? `${vesselName} — ${full}` : full

  return (
    <span
      className={`applicability-badge applicability-badge--${state.toLowerCase()}`}
      role="img"
      aria-label={label}
      title={full}
    >
      {APPLICABILITY_SHORT_LABEL[state]}
    </span>
  )
}
