import type { LucideIcon, LucideProps } from 'lucide-react'

/**
 * 아이콘 한 개 — **`DESIGN_SYSTEM §12` 규격을 여기서 강제한다** (`#747` 2-4).
 *
 * ## 세트는 Lucide다 (2026-09-10 확정 · MIT)
 *
 * `§12`가 규격만 정하고 **세트가 비어 있어** 사이드바와 경고 삼각형 외에는 아이콘을
 * 쓰지 못했다. Heroicons가 stroke 1.5 기본값으로 규격과 정확히 맞지만 약 300개로는
 * 커버리지가 부족하고, Lucide는 약 1,500개에 **한 줄 설정으로** 규격을 맞춘다.
 *
 * ## 왜 컴포넌트를 거치는가
 *
 * Lucide 기본 `strokeWidth`는 **2**다. 호출부마다 `strokeWidth={1.5}`를 적게 두면
 * 적는 곳과 잊는 곳이 갈리고, 그것이 `#694`가 다루는 「클래스 이름 24종」과 같은
 * 경로다. **고를 수 있는 값이 하나뿐이면 틀릴 수가 없다.**
 *
 * ## 장식과 의미를 구분한다
 *
 * `§12`가 *「의미 전달 아이콘에는 반드시 텍스트 라벨 또는 `aria-label` 병기」*를
 * 요구한다. `label`을 주면 `role="img"`가 함께 붙고, 주지 않으면 `aria-hidden`이
 * 된다 — `role` 없이 `aria-label`만 붙은 요소는 **낭독되지 않는다**(`#829` ⑸b).
 */
export function Icon({
  glyph: Glyph,
  label,
  size = 20,
  className,
}: {
  glyph: LucideIcon
  /** 의미를 전달하는 아이콘이면 준다. 장식이면 비운다. */
  label?: string
  size?: number
  className?: string
}) {
  const a11y: LucideProps = label
    ? { role: 'img', 'aria-label': label }
    : { 'aria-hidden': true, focusable: false }

  // `§12` — 라인 아이콘 · stroke 1.5~1.6 · 24px 그리드 · 단색.
  return <Glyph className={className} size={size} strokeWidth={1.5} {...a11y} />
}
