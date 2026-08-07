import type { Rating } from '../features/voyage-cii/types'

/**
 * 등급 배지에 쓸 SVG 패턴 URL — `DESIGN_SYSTEM §15.1`.
 *
 * `GradeBadge.tsx`와 분리한 이유는 **fast refresh** 때문이다. 한 파일이 컴포넌트와
 * 일반 함수를 함께 내보내면 리액트 새로고침이 모듈 전체를 갈아 끼운다.
 *
 * `§14` — **패턴 없는 등급 표시는 구현 금지.** 색만으로 A~E를 구분하면 적록색맹에서
 * A(녹)와 E(적)가 무너진다. A가 예외인 것은 「패턴 없음」 자체가 A의 식별 표시이고,
 * 배지에 등급 문자가 항상 함께 놓이기 때문이다(`§15.1` — A는 solid).
 */
export function gradePatternUrl(rating: Rating): string | undefined {
  if (rating === 'A') return undefined
  return `url(#grade-${rating.toLowerCase()})`
}
