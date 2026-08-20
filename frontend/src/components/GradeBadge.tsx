import './GradeBadge.css'
import type { Rating } from '../features/voyage-cii/types'

/**
 * CII 등급 배지 — `DESIGN_SYSTEM §8` · `§2.4.2` · `§2.4.3` · `§2.4.4` · `§14`.
 *
 * `§8`이 **Variant = `grade`(a·b·c·d·e·none) × `size`(xs·sm·lg) = 18개**로 확정한다.
 *
 * ## 고정 크기가 아니라 오토 레이아웃이다 (#485)
 *
 * 종전에는 64×64 SVG 뷰박스에 문자를 그렸다. `§8`이 **「오토 레이아웃 필수 — `—`가
 * `A`보다 넓어 고정 크기로 만들면 `none`에서 문자가 잘린다」**로 그 방식을 막는다.
 * 그래서 HTML 요소로 바꿔 **내용에 따라 폭이 늘어나게** 한다.
 *
 * ## 패턴을 넣지 않는다 (`§2.4.4`)
 *
 * 등급 문자 A~E가 항상 함께 놓이므로 색 외 보조 채널이 문자로 충족된다(`§14` —
 * 「문자 **또는** 패턴」). 작은 크기에서 패턴을 겹치면 문자 판독만 나빠진다.
 *
 * 패턴은 **문자가 놓이지 않는 자리** — 지도 마커, 차트 등급 밴드, 등급 확률 스택 바 —
 * 전용이며 `GradePatternDefs`가 담당한다.
 *
 * ## 색
 *
 * `bg` 배경 + `text` 문자 + `border` 테두리다(`§2.4.2`). `fill`은 마커·차트 선 등
 * 면 채움 전용이라 배지에 쓰지 않는다.
 *
 * 기능①·기능②·기능③ · 대시보드 · 실시간 CII · 선박 상세가 같은 배지를 쓴다.
 * 한 곳을 고치면 여섯 화면이 함께 바뀐다.
 */

/** 등급 없음 표기 — `§2.4.3` 🔒. `N/A`나 하이픈이 아니라 **em dash**다. */
export const NO_GRADE_TEXT = '—'

interface GradeBadgeProps {
  /**
   * 표시할 등급. `null`이면 `none` variant다 (`§2.4.3`).
   *
   * **산출 불가 상태에서 A~E 중 하나를 임의로 표시하지 않는다** — 그 규칙을 화면마다
   * 다시 쓰지 않도록 `null`을 받는다.
   */
  rating: Rating | null
  /** 스크린 리더가 읽을 이름. 화면 문맥에 따라 다르다. */
  label?: string
  /**
   * 표시 크기 (`§8`).
   *
   * | | 문자 | 패딩 | radius |
   * |---|---|---|---|
   * | `lg` | 20px | 4·12 | 8 |
   * | `sm` | 13px | 3·8 | 4 |
   * | `xs` | 11px | 2·6 | 4 |
   */
  size?: 'xs' | 'sm' | 'lg'
}

export function GradeBadge({ rating, label, size = 'lg' }: GradeBadgeProps) {
  const variant = rating === null ? 'none' : rating.toLowerCase()
  const text = rating ?? NO_GRADE_TEXT
  const defaultLabel = rating === null ? '등급 없음' : `등급 ${rating}`

  return (
    <span
      className={`grade-badge grade-badge--${size} grade-badge--${variant}`}
      role="img"
      aria-label={label ?? defaultLabel}
      style={{
        backgroundColor: `var(--cii-${variant}-bg)`,
        borderColor: `var(--cii-${variant}-border)`,
        color: `var(--cii-${variant}-text)`,
      }}
    >
      {text}
    </span>
  )
}
