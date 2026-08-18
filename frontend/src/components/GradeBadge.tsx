import './GradeBadge.css'
import type { Rating } from '../features/voyage-cii/types'

/**
 * CII 등급 배지 — `DESIGN_SYSTEM §8` · `§14` · `§15.1`.
 *
 * **패턴 없는 등급 표시는 구현 금지다**(`§14`). 색만으로 A~E를 구분하면 적록색맹에서
 * A(녹)와 E(적)가 무너진다. 채움색 위에 `GradePatternDefs`의 패턴을 덮고 등급 문자를
 * 함께 둔다 — 채널이 **색·패턴·문자 셋**이다.
 *
 * A는 패턴이 없다(`§15.1` — solid). 「패턴 없음」 자체가 A의 식별 표시이고 문자가
 * 항상 함께 놓인다.
 *
 * 기능①(`#136`)과 기능②(`#156`)가 같은 배지를 쓴다. 두 화면이 각자 그리면 한쪽만
 * 패턴을 빠뜨려도 드러나지 않는다.
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
