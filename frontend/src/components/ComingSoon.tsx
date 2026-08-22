import './ComingSoon.css'
import type { ScreenMeta } from '../screens'

/**
 * 아직 열지 않은 화면의 안내.
 *
 * 빈 화면을 두지 않는다 — 라우팅이 동작하는데 아무것도 안 보이면 구현 실패와
 * 구분되지 않는다. 이 화면이 무엇을 할 자리인지 밝히는 것까지가 역할이다.
 *
 * ## 내부 정보를 화면에 싣지 않는다
 *
 * 종전에는 이슈 번호(`#351`)와 `UIFLOW 2-4` 같은 내부 참조를 그대로 노출했다.
 * 개발 중에는 유용했으나 **사용자에게는 의미가 없고 미완성 인상만 준다.**
 * 그 정보는 코드 주석과 정본에 남기고 화면에서는 뺀다.
 */

interface ComingSoonProps {
  screen: ScreenMeta
  /** 사용자에게 의미 있는 한 줄 안내. 내부 이슈 번호를 쓰지 않는다. */
  note?: string
}

/**
 * ⚠️ **소비처가 0이지만 지우지 않는다 (#594 판정).** `#506`(`PR #612`)이 설정 화면
 * 스텁을 없애며 마지막 호출부가 사라졌다.
 *
 * 남기는 이유는 이것이 **「구현이 아직 없다」를 표현할 유일한 수단**이기 때문이다.
 * `screens.ts`의 `implemented` 필드가 이 컴포넌트를 판정 기준으로 인용하고,
 * `screens.test.ts`의 `isComingSoonStub()`이 **페이지 파일에 `ComingSoon` 문자열이
 * 있는지**로 스텁 여부를 가른다. 지우면 그 판정 방식도 함께 없애야 한다.
 *
 * 지금은 그런 화면이 0개지만 MVP 밖 화면(`#513` 함대 감축 계획 · 데이터 점검)이
 * 들어오면 다시 필요하다 — 「지금 안 쓰이니 지운다」와 「곧 다시 쓸 것이라
 * 남긴다」의 경계에서 뒤를 택했다.
 */
export function ComingSoon({ screen, note }: ComingSoonProps) {
  return (
    <section className="coming-soon" aria-labelledby="coming-soon-title">
      <p className="coming-soon__badge">준비 중</p>
      <h2 id="coming-soon-title" className="coming-soon__title">
        {screen.label}
      </h2>
      <p className="coming-soon__purpose">{screen.purpose}</p>
      {note ? <p className="coming-soon__note">{note}</p> : null}
    </section>
  )
}
