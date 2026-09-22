import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 텍스트 버튼 높이 — `DESIGN_SYSTEM §8` 〔확정〕 (2026-09-22 · `#1297`).
 *
 * **같은 줄에 놓인 컨트롤과 높이가 같다.** 값을 단언하지 않고 **같다는 것**을 단언한다 —
 * 값을 박으면 이웃이 바뀔 때 이 검사가 규격 대신 옛 값을 지킨다.
 *
 * jsdom에는 레이아웃이 없어 높이를 잴 수 없다. 그래서 **높이를 정하는 선언**을 대조한다.
 *
 * | 자리 | 높이를 정하는 것 |
 * |---|---|
 * | 상단바 — 로그아웃 · 계정 트리거 | `block-size` |
 * | 항차 카드 — 텍스트 버튼 · 같은 줄 카드 버튼 | 위아래 여백 · 테두리 두께 · 글자 크기 |
 *
 * 종전 실측(폰트 적재 후 렌더링): 계정 트리거 40 · 로그아웃 32 · 카드 텍스트 버튼 24 · 카드 버튼 26.
 */
const read = (path: string) =>
  readFileSync(join(process.cwd(), path), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

/** 선택자 목록에 `selector`가 그 자체로 들어 있는 첫 규칙의 본문. */
function ruleOf(css: string, selector: string): string {
  for (const [, selectors, body] of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const list = selectors.split(',').map((s) => s.trim())
    if (list.includes(selector)) return body
  }
  throw new Error(`규칙을 찾지 못했습니다: ${selector}`)
}

function decl(body: string, prop: string): string | null {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(body)
  return m ? m[1].trim() : null
}

/** `padding` 축약에서 위아래 값. 두 값 이상이면 첫 값이 위아래다. */
function paddingBlock(body: string): string | null {
  const block = decl(body, 'padding-block')
  if (block !== null) return block
  const padding = decl(body, 'padding')
  return padding === null ? null : padding.split(/\s+(?![^(]*\))/)[0]
}

/** `border` 축약 또는 `border-width`의 두께. `0`·`none`은 `0`이다. */
function borderWidth(body: string): string {
  const width = decl(body, 'border-width')
  if (width !== null) return width
  const border = decl(body, 'border')
  if (border === null || border === '0' || border === 'none') return '0'
  return border.split(/\s+(?![^(]*\))/)[0]
}

describe('텍스트 버튼 높이 — 같은 줄의 컨트롤과 같다 (DESIGN_SYSTEM §8 · #1297)', () => {
  it('상단바 — 로그아웃과 계정 트리거의 높이 선언이 같다', () => {
    const logout = ruleOf(read('src/layout/AppShell.css'), '.app-shell__logout')
    const trigger = ruleOf(read('src/layout/AccountMenu.css'), '.account-menu__trigger')

    expect(decl(logout, 'block-size'), '로그아웃 높이 선언이 없습니다').not.toBeNull()
    expect(decl(trigger, 'block-size')).toBe(decl(logout, 'block-size'))
    // 높이를 준 뒤 위아래 여백이 남으면 상자가 그만큼 커진다 — 여백은 0이어야 한다.
    expect(paddingBlock(trigger)).toBe('0')
  })

  it('항차 카드 — 텍스트 버튼이 같은 줄 카드 버튼과 같은 상자를 쓴다', () => {
    const css = read('src/features/voyage-management/VoyagePanel.css')
    const text = ruleOf(css, '.vy__text-action')
    // 「이 항차 취소」·「확정 되돌리기」 옆 주 버튼과 확인 줄의 실행 버튼이 이 규칙을 쓴다.
    const neighbor = ruleOf(css, '.vy__transition')

    expect(paddingBlock(text)).toBe(paddingBlock(neighbor))
    expect(borderWidth(text)).toBe(borderWidth(neighbor))
    expect(decl(text, 'font-size')).toBe(decl(neighbor, 'font-size'))
  })
})
