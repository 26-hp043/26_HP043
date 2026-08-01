import './ComingSoon.css'
import type { ScreenMeta } from '../screens'

/**
 * 미구현 화면의 "준비 중" 표시 (#133).
 *
 * 빈 화면을 두지 않는다 — 라우팅이 동작하는데 아무것도 안 보이면 구현 실패와
 * 구분되지 않는다. 화면의 목적과 어느 이슈가 채우는지를 함께 보여 준다.
 */

interface ComingSoonProps {
  screen: ScreenMeta
  /** 이 화면을 구현하는 이슈 번호. 아직 이슈가 없으면 생략한다. */
  issues?: string[]
  /** 후속 이슈가 아직 없을 때의 사유·시점 설명. */
  note?: string
}

export function ComingSoon({ screen, issues, note }: ComingSoonProps) {
  return (
    <section className="coming-soon" aria-labelledby="coming-soon-title">
      <p className="coming-soon__badge">준비 중</p>
      <h2 id="coming-soon-title" className="coming-soon__title">
        {screen.label}
        <span className="coming-soon__title-en"> {screen.labelEn}</span>
      </h2>
      <p className="coming-soon__purpose">{screen.purpose}</p>

      <dl className="coming-soon__meta">
        <dt>화면 ID</dt>
        <dd>{screen.id}</dd>
        {issues?.length ? (
          <>
            <dt>구현 이슈</dt>
            <dd>{issues.join(' · ')}</dd>
          </>
        ) : null}
      </dl>

      {note ? <p className="coming-soon__note">{note}</p> : null}
    </section>
  )
}
