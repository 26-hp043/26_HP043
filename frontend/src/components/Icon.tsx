import type { LucideIcon, LucideProps } from 'lucide-react'
import './Icon.css'

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
 * Lucide 기본 `strokeWidth`는 **2**라 규격(`1.5`)과 다르다. 호출부마다 적게 두면
 * 적는 곳과 잊는 곳이 갈리고, 그것이 `#694`가 다루는 「클래스 이름 24종」과 같은
 * 경로다. **고를 수 있는 값이 하나뿐이면 틀릴 수가 없다.**
 *
 * ## 규격값은 이 파일에 없다 (`#1174`)
 *
 * 종전에는 이 컴포넌트가 `size = 20`·`strokeWidth={1.5}`를 **숫자로** 들고 있었다.
 * 같은 값이 Figma 생성 토큰(`--icon-default`·`--icon-stroke`)으로도 내려오므로
 * **규격 하나가 두 곳에** 있었고, 디자이너가 Figma에서 두께를 바꾸면 토큰을 읽는
 * 커스텀 아이콘만 따라가고 세트 아이콘은 옛 값으로 남았다 — 화면은 깨지지 않는다.
 *
 * 값은 전부 `Icon.css`가 토큰으로 먹인다. 이 파일은 **이름만** 고른다.
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
  size = 'default',
  className,
}: {
  glyph: LucideIcon
  /** 의미를 전달하는 아이콘이면 준다. 장식이면 비운다. */
  label?: string
  /**
   * `§12` 규격의 크기 **이름**. 숫자를 받지 않는다 (`#1174`).
   *
   * 값은 Figma가 갖는다(`--icon-inline` · `--icon-default` · `--icon-large`).
   * 숫자를 받으면 같은 규격값이 **코드에도** 있게 되고, Figma에서 치수를 바꾸면
   * 토큰을 읽는 커스텀 아이콘만 따라가고 세트 아이콘은 옛 값으로 남는다.
   *
   * 이름 셋은 생성 토큰의 이름 셋과 같아야 하며 `icon.sync.test.ts`가 잠근다 —
   * Figma에 크기가 늘거나 줄면 그때 실패한다.
   */
  size?: 'inline' | 'default' | 'large'
  className?: string
}) {
  const a11y: LucideProps = label
    ? { role: 'img', 'aria-label': label }
    : { 'aria-hidden': true, focusable: false }

  /*
   * `§12` — 라인 아이콘 · stroke 1.5~1.6 · 24px 그리드 · 단색.
   *
   * **크기도 두께도 여기서 적지 않는다** (`#1174`). Lucide가 붙이는 기본 속성
   * (`width`/`height` 24 · `stroke-width` 2)을 `Icon.css`가 토큰으로 덮는다 —
   * CSS 선언이 SVG 표현 속성을 이긴다(Chromium 실측). 그래서 규격값의 출처가
   * **Figma 하나**로 모인다(`§15`).
   *
   * `icon` 클래스는 **항상** 붙는다 — 정렬·크기·두께 규격이 거기 있다. 호출부가
   * 주는 `className`은 색·여백처럼 자리마다 다른 것만 얹는다.
   */
  return (
    <Glyph
      className={['icon', `icon--${size}`, className].filter(Boolean).join(' ')}
      {...a11y}
    />
  )
}
