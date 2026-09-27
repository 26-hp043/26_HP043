import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 좁은 창의 셸 — `1100px` 이하에서 사이드바가 축소(64)로 서고, 상단바 셀렉트가 줄어든다
 * (`DESIGN_SYSTEM §7.2` 〔확정〕 2026-09-26 · #1885).
 *
 * 400px 창에서 페이지가 547까지 가로로 넘쳤다. jsdom은 레이아웃을 계산하지 않아 넘침 자체는
 * 여기서 재지 못한다 — 실제 브라우저 실측은 PR 본문에 남긴다. 이 검사는 **그 결과를 만든
 * 규칙이 조용히 사라지지 않게** 잠근다. 화면이 깨지지 않는 쪽(넓은 창)에서는 규칙이 없어져도
 * 아무도 알아채지 못한다.
 */
const css = readFileSync(join(import.meta.dirname, 'AppShell.css'), 'utf8')

function narrowBlock(): string {
  const start = css.indexOf('@media (max-width: 1100px) {')
  expect(start, '1100px 이하 규칙이 있다').toBeGreaterThan(-1)
  // 다음 최상위 규칙(줄 첫머리의 `}`)까지가 이 미디어 블록이다
  const end = css.indexOf('\n}', start)
  return css.slice(start, end)
}

function rule(source: string, selector: string): string {
  const start = source.indexOf(`${selector} {`)
  expect(start, `${selector} 규칙이 있다`).toBeGreaterThan(-1)
  return source.slice(start, source.indexOf('}', start))
}

describe('좁은 창의 셸 (#1885 · DESIGN_SYSTEM §7.2)', () => {
  it('1100px 이하에서 사이드바가 축소 폭 토큰으로 선다', () => {
    const sidebar = rule(narrowBlock(), '.app-shell__sidebar')
    expect(sidebar).toMatch(/width:\s*var\(--layout-sidebar-width-collapsed\)/)
    expect(sidebar).toMatch(/flex-basis:\s*var\(--layout-sidebar-width-collapsed\)/)
  })

  it('라벨은 **지우지 않고** 시각적으로만 감춘다 — 아이콘이 aria-hidden이라 이름이 남아야 한다', () => {
    const block = narrowBlock()
    expect(block).toContain('.app-shell__nav-text')
    expect(block).not.toMatch(/display:\s*none/)
    expect(block).not.toMatch(/visibility:\s*hidden/)
    expect(block).toMatch(/clip:\s*rect\(0,\s*0,\s*0,\s*0\)/)
  })

  it('축소 규칙이 **기본 규칙보다 뒤에** 있다 — 앞에 두면 같은 우선순위의 기본 여백이 이긴다', () => {
    // 처음 구현에서 사이드바 규칙 옆에 두었다가 400px 실측에서 로고가 22px로 찍혔다
    const media = css.indexOf('@media (max-width: 1100px) {')
    for (const selector of ['.app-shell__brand {', '.app-shell__nav-link {']) {
      const base = css.indexOf(selector)
      expect(base, `${selector} 기본 규칙이 있다`).toBeGreaterThan(-1)
      expect(media, `${selector}보다 뒤`).toBeGreaterThan(base)
    }
  })

  /*
   * `#1978` — 축소되면 「준비 중」·「사무직 전용」 태그가 위 규칙으로 감춰져, 잠긴 항목을
   * 가르는 **화면 채널이 색 하나**가 된다. 그 색차는 활성 `#5f5e5a` ↔ 비활성 `#8b8a83`로
   * **1.87:1**(다크 1.85)이라 비텍스트 기준 3:1에도 못 미친다. 배지가 형태 채널을 더한다.
   *
   * 배지를 **여기서만** 켜는 것이 핵심이다 — 펼친 상태에서 함께 켜지면 태그와 배지가
   * 같은 말을 두 번 한다.
   */
  it('축소 상태에서만 자물쇠 배지를 켠다 — 색 하나로 잠김을 말하지 않는다 (#1978)', () => {
    const lockInNarrow = rule(narrowBlock(), '.app-shell__nav-lock')
    expect(lockInNarrow).toMatch(/display:\s*block/)
    expect(lockInNarrow).toMatch(/position:\s*absolute/)

    // 펼친 상태(미디어 블록 **밖**)에서는 꺼져 있다
    const base = css.slice(0, css.indexOf('@media (max-width: 1100px) {'))
    expect(rule(base, '.app-shell__nav-lock')).toMatch(/display:\s*none/)
  })

  it('배지가 앉을 상자가 자리를 잡고 있다 — 없으면 링크 기준으로 떠 버린다', () => {
    const base = css.slice(0, css.indexOf('@media (max-width: 1100px) {'))
    expect(rule(base, '.app-shell__nav-iconwrap')).toMatch(/position:\s*relative/)
  })

  it('상단바 셀렉트는 상한(180)을 두되 컨테이너에 맞춰 줄어든다', () => {
    const select = rule(css, '.app-shell__util-select')
    expect(select).toMatch(/max-width:\s*180px/)
    expect(select).toMatch(/min-inline-size:\s*0/)
    expect(select).toMatch(/flex:\s*0 1 auto/)
  })
})
