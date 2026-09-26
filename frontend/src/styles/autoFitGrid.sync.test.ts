import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 자동 채움 격자의 최소 폭은 컨테이너보다 넓어지지 않는다 (#1943).
 *
 * `repeat(auto-fit, minmax(240px, 1fr))`은 칸 하나의 **하한이 240px**라, 본문 열이 그보다
 * 좁아지면(360px 창 · 사이드바 64 · 여백) 칸이 줄지 못하고 페이지를 가로로 밀어낸다.
 * 연간 등급 관리(377)와 보고서(369)가 그렇게 넘쳤다. `min(240px, 100%)`로 쓰면 넓은 창에서는
 * 종전과 **완전히 같고**, 좁은 창에서만 컨테이너 폭까지 줄어든다.
 *
 * 화면이 깨지는 것은 좁은 창뿐이라 넓은 창에서 새 격자를 쓰면 아무도 알아채지 못한다 —
 * 그래서 CSS 전부를 훑어 모양으로 막는다.
 */
const SRC = join(import.meta.dirname, '..')

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return cssFiles(path)
    return name.endsWith('.css') ? [path] : []
  })
}

// 주석 안의 예시는 세지 않는다
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

describe('자동 채움 격자의 최소 폭 (#1943)', () => {
  it('repeat(auto-fit|auto-fill, minmax(고정 길이, …))를 쓰지 않는다 — min(길이, 100%)로 감싼다', () => {
    const offenders: string[] = []
    for (const file of cssFiles(SRC)) {
      const css = stripComments(readFileSync(file, 'utf8'))
      for (const m of css.matchAll(/repeat\(\s*auto-(?:fit|fill)\s*,\s*minmax\(\s*([^,]+?)\s*,/g)) {
        if (!m[1].startsWith('min(')) offenders.push(`${relative(SRC, file)}: ${m[0]}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('검사가 실제로 격자를 찾는다 — 0건으로 공허하게 통과하지 않는다', () => {
    const found = cssFiles(SRC).filter((f) => /repeat\(\s*auto-fit/.test(readFileSync(f, 'utf8')))
    expect(found.length).toBeGreaterThan(5)
  })
})
