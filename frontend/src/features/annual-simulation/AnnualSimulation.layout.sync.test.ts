/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 연간 등급 관리의 배치 규칙을 CSS에서 잠근다 (#1700).
 *
 * jsdom은 스타일시트를 계산하지 않으므로, 화면 검사(`AnnualSimulation.test.tsx`)는
 * **어느 클래스가 어디에 있는가**까지만 본다. 그 클래스가 정본의 값을 쓰는지는
 * 여기서 규칙 본문을 읽어 확인한다.
 */

const CSS = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'AnnualSimulation.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 미디어 쿼리 밖, 선택자가 정확히 일치하는 첫 규칙의 본문. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(CSS)
  if (!match) throw new Error(`규칙이 없다: ${selector}`)
  return match[2]
}

// 입력-결과 2단은 화면들을 한 표로 대조한다 — `styles/inputColumn.sync.test.ts` (#1711).
// 결론 띠의 크기 · pill 규칙은 공용 부품이 잠근다 — `components/VerdictStrip.sync.test.ts` (#1711).

describe('카드 예산 — `DESIGN_SYSTEM §5`', () => {
  it('「라벨 · 값」 줄은 면을 띄우지 않는다 — 배경 · 그림자 없이 구분선만', () => {
    const body = rule('.annual-sim__row')
    expect(body).not.toMatch(/background|box-shadow|border-radius/)
    expect(body).toMatch(/border-bottom:/)
  })
})

describe('스택 바 구간 안 문자 — `DESIGN_SYSTEM §10.2` 🔒 · `§14`', () => {
  it('글자 뒤에 표면색 바탕을 깐다 — 후광만으로는 사선 무늬 틈이 비친다', () => {
    const body = rule('.annual-sim__seg-label')
    expect(body).toMatch(/background:\s*var\(--color-surface\)/)
    expect(body).toMatch(/color:\s*var\(--color-text\)/)
    expect(body).not.toMatch(/text-stroke/)
  })
})
