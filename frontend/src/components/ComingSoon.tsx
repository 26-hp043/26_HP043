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
