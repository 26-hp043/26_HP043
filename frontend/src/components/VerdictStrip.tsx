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
  /**
   * 등급. **`null`을 넘기면 「없음」 배지**가 서고, 넘기지 않으면 배지 자체가 없다 (#1729) —
   * 「등급이 없는 배」와 「등급이 이 자리의 값이 아닌 화면」은 다르다.
   */
  rating?: Rating | null
  /** 배지의 낭독 이름. 없으면 `label + 등급`. */
  ratingLabel?: string
  /**
   * 값이 비율일 때 함께 그리는 막대 (0~1 · #1729).
   *
   * 숫자를 그림으로 한 번 더 말한다 — 진행률처럼 「어디쯤인가」가 곧 뜻인 값이 그렇다.
   * `role="progressbar"`와 값을 함께 낸다(#829 ⑸b — 이름만 읽히고 몇 퍼센트인지는
   * 읽히지 않던 자리다).
   */
  meter?: { ratio: number; label: string }
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
   *
   * **그 화면의 데이터에 값이 있을 때만 넘긴다** (`§8.6` · #1728). 없는 화면(선박 상세 —
   * `API_SPEC §2.7`에 `risk_level`이 없다)은 비워 두며, 다른 경로를 더 불러 채우지 않는다.
   */
  risk?: { level: RiskLevel; heading: string; text: string; withIcon: boolean }
}

export function VerdictStrip({ label, main, sub, risk }: VerdictStripProps) {
  return (
    <section className="verdict-strip" aria-label={label}>
      <div className="verdict-strip__main">
        <span className="verdict-strip__label">{main.label}</span>
        <span className="verdict-strip__pair">
          {main.rating !== undefined ? (
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
          {sub.rating !== undefined ? (
            <GradeBadge
              rating={sub.rating}
              size="sm"
              label={sub.ratingLabel ?? `${sub.label} ${sub.rating}`}
            />
          ) : null}
          <span className="verdict-strip__sub-value">{sub.value}</span>
          {sub.unit ? <span className="verdict-strip__unit">{sub.unit}</span> : null}
        </span>
        {sub.meter ? (
          <span
            className="verdict-strip__meter"
            role="progressbar"
            aria-label={sub.meter.label}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(sub.meter.ratio * 100)}
          >
            <span
              className="verdict-strip__meter-bar"
              style={{ inlineSize: `${Math.min(1, Math.max(0, sub.meter.ratio)) * 100}%` }}
            />
          </span>
        ) : null}
      </div>
      {/*
        위험도 pill — `§2.5 (b)`의 단계별 색(HIGH Warning · CRITICAL Danger)은 **글자에만**
        입힌다. 면과 테두리는 중립이다(`§2.3` 경고색은 한 자리에 한 번). 아이콘은 라벨이
        옆에 있어 장식이다 — `Icon`이 `aria-hidden`을 붙인다.
      */}
      {risk ? (
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
      ) : null}
    </section>
  )
}
