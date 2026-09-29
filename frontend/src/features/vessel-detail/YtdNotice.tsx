/**
 * 올해(YTD) 값의 고지 — **한 문장을 두 화면이 공유한다** (`#2017` 리뷰).
 *
 * 근거는 `PRD §3.3.7` 각주(「YTD 등급은 연중 누적 예측값으로 공식 등급이 아니다 — 공식 등급은
 * 연말 DCS 보고·검증 후 확정된다」)와 `PRD COR-2`(연중 화면의 등급은 「현재 누적 기준 예상
 * 등급」으로 표기)다. 문장 자체의 원문은 `PRD §6.3`에 없어 **표시 문구**이지만(`AGENTS §4.6`),
 * 선박 상세(`2-8`)와 연간 등급 관리(`2-3`)가 같은 값을 두고 다른 말을 하지 않도록 여기 한 곳에
 * 둔다 — 같은 값이 화면마다 다르게 보이면 사용자는 둘 중 하나가 틀렸다고 읽는다(`#750` · `#866`).
 *
 * 검사는 문장을 리터럴로 단언하지 않고 `data-testid`로 **있는지**를 본다.
 */
export const YTD_NOTICE_TEST_ID = 'ytd-notice'

export function YtdNotice({ className }: { className?: string }) {
  return (
    <p className={className} data-testid={YTD_NOTICE_TEST_ID}>
      올해 값은 연중 누적 예측값이며 <b>공식 등급이 아닙니다</b>. 공식 등급은 연말
      DCS 보고·검증 후 확정됩니다.
    </p>
  )
}
