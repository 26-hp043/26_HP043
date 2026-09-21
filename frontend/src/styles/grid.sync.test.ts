/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import blueLogRaw from '../design/tokens/BlueLog.tokens.json?raw'

/**
 * 셸 폭 산술 ↔ Figma 그리드 변수 드리프트 가드 (`#1450`).
 *
 * ## 왜 필요한가
 *
 * 같은 폭이 **네 갈래**로 적혀 있었다 — `DESIGN_SYSTEM §7.1` 🔒 산술은 외곽 여백 0을
 * 전제한 `240 + 24 + 1656`, 같은 문서 `§6`은 외곽 여백 24, 구현은 24, Figma 변수
 * `grid/content-width` · `grid/margin`은 `#707` 이전 값(1680 · 32)에 멈춰 있었다.
 * 두 변수는 **코드가 읽지 않아** 틀려도 화면에 드러나지 않았다 — 그래서 아무도 몰랐다.
 *
 * ## 무엇을 보는가
 *
 * ⑴ Figma 변수끼리 산술이 닫힌다: `margin + gnb + gutter + content + margin = frame`
 * ⑵ `§7.1` 그리드 표의 「콘텐츠 영역」 · 「외곽 여백」이 Figma 값과 같다
 * ⑶ `§7.1`의 산술 문장이 같은 값을 적는다
 *
 * 사이드바↔본문 간격은 `§6`이 소유하는 「패널 간 gap」이고 값은 그리드 거터와 같다
 * (`AppShell.css`의 `--shell-gutter: var(--grid-gutter)`).
 */

type Leaf = { $value: number }
const grid = (JSON.parse(blueLogRaw) as { grid: Record<string, Leaf> }).grid
const v = (key: string) => {
  const leaf = grid[key]
  if (!leaf) throw new Error(`BlueLog.tokens.json에 grid/${key}가 없다`)
  return leaf.$value
}

const HERE = fileURLToPath(new URL('.', import.meta.url))
const DESIGN = readFileSync(join(HERE, '..', '..', '..', 'DESIGN_SYSTEM.md'), 'utf-8')

/** `§7.1` 그리드 표의 한 행 값(첫 숫자). */
function gridRow(label: string): number {
  const match = new RegExp(`^\\|\\s*${label}\\s*\\|\\s*([0-9]+)`, 'm').exec(DESIGN)
  if (!match) throw new Error(`DESIGN_SYSTEM §7.1 그리드 표에서 「${label}」 행을 찾지 못했다`)
  return Number(match[1])
}

describe('셸 폭 산술 (#1450)', () => {
  it('Figma 그리드 변수끼리 1920이 닫힌다', () => {
    expect(v('margin') * 2 + v('gnb-expanded') + v('gutter') + v('content-width')).toBe(v('frame-width'))
  })

  it('DESIGN_SYSTEM §7.1 그리드 표가 Figma 값과 같다', () => {
    expect(gridRow('콘텐츠 영역')).toBe(v('content-width'))
    expect(gridRow('외곽 여백')).toBe(v('margin'))
    expect(gridRow('패널 간 gap')).toBe(v('gutter'))
  })

  it('DESIGN_SYSTEM §7.1 산술 문장이 같은 값을 적는다', () => {
    const [m, g, gap, c] = [v('margin'), v('gnb-expanded'), v('gutter'), v('content-width')]
    expect(DESIGN).toContain(`\`${m} + ${g} + ${gap} + ${c} + ${m} = ${v('frame-width')}\``)
  })
})
