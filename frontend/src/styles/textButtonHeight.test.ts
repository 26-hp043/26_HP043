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
 * | 계정 메뉴 패널 — 로그아웃(혼자 놓임 · #2203) | `block-size` = `--target-icon-button` |
 * | 항차 카드 — 텍스트 버튼 · 같은 줄 카드 버튼 | 위아래 여백 · 테두리 두께 · 글자 크기 |
 * | 대시보드 지도 — 항로선 재시도(혼자 놓임 · #2154) | `block-size` = `--target-icon-button` |
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
  it('계정 메뉴 — 혼자 놓인 로그아웃은 `--target-icon-button`이다 (#2203)', () => {
    /*
     * 종전에는 상단바에서 계정 트리거와 나란히 놓여 「같은 줄의 이웃과 같다」를 대조했다.
     * #2203에서 로그아웃이 계정 메뉴 패널 안으로 들어가 **혼자 놓인다** — 규칙의 다른 가지
     * 「혼자 놓이면 `--target-icon-button`(32)」가 적용된다.
     */
    const logout = ruleOf(read('src/layout/AccountMenu.css'), '.account-menu__logout')

    expect(decl(logout, 'block-size')).toBe('var(--target-icon-button)')
    // 높이를 준 뒤 위아래 여백이 남으면 상자가 그만큼 커진다 — 여백은 0이어야 한다.
    expect(paddingBlock(logout)).toBe('0')
  })

  it('대시보드 지도 — 항로선 재시도도 혼자 놓여 `--target-icon-button`이다 (#2154)', () => {
    /*
     * `§9.5` 〔확정 2026-10-07 · `#2154`〕가 이 자리를 **`§8` 텍스트 버튼**으로 정했고,
     * 실패 문장과 같은 줄에 다른 컨트롤이 없어 「혼자 놓이면 32」가 걸린다.
     *
     * 이 검사가 없던 동안 그 규격은 **글로만** 있었다 — `§8`의 「쓰는 곳」 목록에 자리를
     * 더하면서 그것을 지키는 검사도 함께 둔다.
     */
    const retry = ruleOf(read('src/features/fleet/FleetMap.css'), '.fleetmap__route-retry')

    expect(decl(retry, 'block-size')).toBe('var(--target-icon-button)')
    // 텍스트 버튼의 모양 — 면도 테두리도 없다 (`§8`).
    expect(decl(retry, 'background')).toBe('transparent')
    expect(borderWidth(retry)).toBe('0')
    expect(decl(retry, 'color')).toBe('var(--text-primary)')
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
