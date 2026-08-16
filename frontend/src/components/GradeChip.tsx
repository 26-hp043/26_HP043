import './GradeChip.css'
import type { Rating } from '../features/voyage-cii/types'

/**
 * 등급 칩 — 목록·분포에 쓰는 작은 표시.
 *
 * `GradeBadge`(64px 정사각 SVG)와 역할이 다르다. 배지는 **결과 화면의 주인공**이고
 * 칩은 **목록 안의 한 항목**이다. 배지를 줄여 쓰면 패턴이 뭉개져 오히려 A~E 구분이
 * 나빠진다.
 *
 * ## 색만으로 구분하지 않는다 (`DESIGN_SYSTEM §14`)
 *
 * 칩은 **등급 문자를 항상 함께** 싣는다. 색이 안 보여도 글자로 읽힌다.
 * 배경·글자·테두리는 디자이너 토큰의 `cii.{등급}.{bg,text,border}` 세 짝을 그대로
 * 쓴다 — 이 셋은 라이트·다크 양쪽에서 대비가 유지되도록 함께 설계된 값이다.
 */

interface GradeChipProps {
  rating: Rating
  /** 스크린 리더용. 목록 문맥에서는 「YTD 등급 D」처럼 무엇의 등급인지 밝힌다. */
  label?: string
  size?: 'md' | 'sm'
}

export function GradeChip({ rating, label, size = 'md' }: GradeChipProps) {
  return (
    <span
      className={`grade-chip grade-chip--${rating.toLowerCase()} grade-chip--${size}`}
      role="img"
      aria-label={label ?? `등급 ${rating}`}
    >
      {rating}
    </span>
  )
}
