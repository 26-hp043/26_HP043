import { AlertTriangle } from 'lucide-react'
import type { Rating, RiskLevel } from '../features/voyage-cii/types'
import { GradeBadge } from './GradeBadge'
import { Icon } from './Icon'
import './VerdictStrip.css'

/**
 * 결론 띠 — `DESIGN_SYSTEM §8.6` 🔒 (#1700 · #1711).
 *
 * 결과가 있는 화면은 **맨 위 한 줄에 답을 적는다.** 주 결론 하나 · 보조 하나 · 위험도
 * pill 하나다. 칸 수를 props 모양으로 고정해 둔다 — 셋째 수치를 끼워 넣을 자리가
 * 없어야 띠가 다시 타일 줄로 돌아가지 않는다.
 *
 * #1700이 연간 등급 관리 안에 처음 만들었고, #1711이 CII 예측과 함께 쓰려고 여기로
 * 옮겼다. 화면마다 다시 그리면 「보조는 주보다 작다」 같은 규칙이 화면 수만큼 흩어진다.
 */

/** 띠의 한 칸. 등급이 있으면 배지와 값이 한 쌍이다(`§14` 색 단독 금지). */
interface VerdictSlot {
  label: string
  value: string
  /** 값 뒤에 작게 붙는 단위. */
  unit?: string
  rating?: Rating
  /** 배지의 낭독 이름. 없으면 `label + 등급`. */
  ratingLabel?: string
}

interface VerdictStripProps {
  /** 띠의 낭독 이름 — 화면에 글자로는 나오지 않는다. */
  label: string
  /** 주 결론 — `display` 크기. */
  main: VerdictSlot
  /** 보조 — `h2` 크기. 주 결론 크기로 커지면 `§8.6` 위반이다. */
  sub: VerdictSlot
  /**
   * 위험도 — 문구는 부르는 쪽이 `riskLabel`로 만든다. 판정 기준이 화면마다 달라서다
   * (`PRD §9.4.1` 결정론 · `§9.4.2` 확률).
   */
  risk: { level: RiskLevel; heading: string; text: string; withIcon: boolean }
}

export function VerdictStrip({ label, main, sub, risk }: VerdictStripProps) {
  return (
    <section className="verdict-strip" aria-label={label}>
      <div className="verdict-strip__main">
        <span className="verdict-strip__label">{main.label}</span>
        <span className="verdict-strip__pair">
          {main.rating ? (
            <GradeBadge
              rating={main.rating}
              size="lg"
              label={main.ratingLabel ?? `${main.label} ${main.rating}`}
            />
          ) : null}
          <span className="verdict-strip__value">{main.value}</span>
          {main.unit ? <span className="verdict-strip__unit">{main.unit}</span> : null}
        </span>
      </div>
      <div className="verdict-strip__sub">
        <span className="verdict-strip__label">{sub.label}</span>
        <span className="verdict-strip__pair">
          {sub.rating ? (
            <GradeBadge
              rating={sub.rating}
              size="sm"
              label={sub.ratingLabel ?? `${sub.label} ${sub.rating}`}
            />
          ) : null}
          <span className="verdict-strip__sub-value">{sub.value}</span>
          {sub.unit ? <span className="verdict-strip__unit">{sub.unit}</span> : null}
        </span>
      </div>
      {/*
        위험도 pill — `§2.5 (b)`의 단계별 색(HIGH Warning · CRITICAL Danger)은 **글자에만**
        입힌다. 면과 테두리는 중립이다(`§2.3` 경고색은 한 자리에 한 번). 아이콘은 라벨이
        옆에 있어 장식이다 — `Icon`이 `aria-hidden`을 붙인다.
      */}
      <p className="verdict-strip__risk">
        <span className="verdict-strip__risk-label">{risk.heading}</span>
        {risk.withIcon ? (
          <span className="verdict-strip__risk-icon">
            <Icon glyph={AlertTriangle} size="inline" />
          </span>
        ) : null}
        <span
          className={`verdict-strip__risk-value verdict-strip__risk-value--${risk.level.toLowerCase()}`}
        >
          {risk.text}
        </span>
      </p>
    </section>
  )
}
