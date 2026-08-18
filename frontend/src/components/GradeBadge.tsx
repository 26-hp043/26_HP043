import './GradeBadge.css'
import type { Rating } from '../features/voyage-cii/types'

/**
 * CII 등급 배지 — `DESIGN_SYSTEM §8` · `§2.4.2` · `§2.4.4` · `§14`.
 *
 * **패턴을 넣지 않는다**(`§2.4.4`). 등급 문자 A~E가 항상 함께 놓이므로 색 외 보조
 * 채널이 문자로 충족된다(`§14` — 「문자 **또는** 패턴」). 작은 크기에서 패턴을
 * 겹치면 문자 판독만 나빠진다.
 *
 * 패턴은 **문자가 놓이지 않는 자리** — 지도 마커, 차트 등급 밴드, 등급 확률 스택 바 —
 * 전용이며 `GradePatternDefs`가 담당한다.
 *
 * 색은 `bg` 배경 + `text` 문자 + `border` 테두리다(`§2.4.2`). `fill`은 마커·차트 선
 * 등 면 채움 전용이라 배지에 쓰지 않는다.
 *
 * 기능①·기능②·기능③ · 대시보드 · 실시간 CII · 선박 상세가 같은 배지를 쓴다.
 * 한 곳을 고치면 여섯 화면이 함께 바뀐다.
 */

interface GradeBadgeProps {
  rating: Rating
  /** 스크린 리더가 읽을 이름. 화면 문맥에 따라 다르다. */
  label?: string
  /** 표시 크기. 기능②의 비교 카드처럼 여러 개가 나란히 놓이면 작게 쓴다. */
  size?: 'md' | 'sm'
}

export function GradeBadge({ rating, label, size = 'md' }: GradeBadgeProps) {
  const lower = rating.toLowerCase()

  return (
    <svg
      className={`grade-badge grade-badge--${size}`}
      viewBox="0 0 64 64"
      role="img"
      aria-label={label ?? `등급 ${rating}`}
    >
      <rect
        width="64"
        height="64"
        rx="8"
        fill={`var(--cii-${lower}-bg)`}
        stroke={`var(--cii-${lower}-border)`}
        strokeWidth="1"
      />
      <text
        x="32"
        y="32"
        textAnchor="middle"
        dominantBaseline="central"
        fill={`var(--cii-${lower}-text)`}
        fontSize="34"
        fontWeight="500"
        fontFamily="var(--font-sans)"
      >
        {rating}
      </text>
    </svg>
  )
}
