import './DisclaimerBanner.css'

/**
 * 면책 배너 — DESIGN_SYSTEM.md §13 · PRD.md §6.3.
 *
 * §13은 "모든 결과 화면 하단에 면책 문구 상시 노출"을 🔒(고정) 항목으로 규정한다.
 * 닫기 버튼을 두지 않는 것은 그 때문이다.
 *
 * **이 이슈(#133)는 구조만 배치한다.** 응답의 `disclaimer` 필드를 우선 쓰고 없으면
 * 기본 문구로 대체하는 선택 로직은 결과 화면 이슈(#136) 소관이다. 여기서는 그
 * 로직이 값을 넘겨줄 자리로 `text` prop만 열어 두고, 미지정 시 PRD §6.3 문구를 쓴다.
 */

/** PRD §6.3 — "모든 결과 화면" 행의 문구를 그대로 복사했다. */
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
const DEFAULT_DISCLAIMER =
  '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.'

interface DisclaimerBannerProps {
  /** 서버 응답의 `disclaimer`. 비어 있으면 PRD §6.3 기본 문구를 쓴다. */
  text?: string
}

export function DisclaimerBanner({ text }: DisclaimerBannerProps) {
  const message = text?.trim() ? text : DEFAULT_DISCLAIMER

  return (
    <p className="disclaimer-banner" role="note">
      {message}
    </p>
  )
}
