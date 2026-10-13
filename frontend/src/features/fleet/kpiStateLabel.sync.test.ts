import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 「운항 상태」의 「운항 중」·「정박 중」은 낱말 사이에서 꺾이지 않는다 (#2433).
 *
 * ## 무엇을 막는가
 *
 * 1000~1440 폭에서 「운항 상태」 칸이 좁아 두 쌍(아이콘 · 숫자 · 레이블)이 한 줄에 들어가지
 * 않는다. 줄바꿈을 풀어 두면 브라우저가 레이블을 「운항 / 중」으로 꺾어 숫자 옆에 두 줄을
 * 세운다. 레이블은 한 줄로 묶고, 자리가 모자라면 **쌍이** 다음 줄로 넘어가야 한다 — 둘 중
 * 하나만 남으면 레이블이 다시 꺾이거나 쌍이 칸 밖으로 나간다.
 */
const CSS = readFileSync(join(process.cwd(), 'src/features/fleet/FleetDashboard.css'), 'utf-8')
const code = CSS.replace(/\/\*[\s\S]*?\*\//g, '')

/** 선택자가 정확히 이것 하나인 규칙의 본문. */
function rule(selector: string): string {
  for (const [, selectors, body] of code.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (selectors.trim() === selector) return body
  }
  throw new Error(`규칙을 찾지 못했습니다: ${selector}`)
}

describe('「운항 상태」 레이블은 한 줄이다 (#2433)', () => {
  it('레이블은 낱말 사이에서 꺾이지 않는다', () => {
    expect(rule('.kpi__state-label')).toMatch(/white-space:\s*nowrap/)
  })

  it('자리가 모자라면 쌍이 줄을 넘긴다 — 칸 밖으로 나가지 않는다', () => {
    expect(rule('.kpi__states')).toMatch(/flex-wrap:\s*wrap/)
  })
})
