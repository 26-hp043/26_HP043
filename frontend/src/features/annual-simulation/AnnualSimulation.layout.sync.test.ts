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

describe('입력-결과 2단 — `DESIGN_SYSTEM §8.7`', () => {
  it('입력 기둥은 `--grid-input-column` 고정 폭이다 — 12컬럼 비율(5:7)이 아니다', () => {
    const body = rule('.annual-sim')
    expect(body).toMatch(/grid-template-columns:\s*var\(--grid-input-column\)\s+minmax\(0,\s*1fr\)/)
    expect(CSS).not.toMatch(/--grid-split-(primary|secondary)/)
  })

  it('입력 기둥은 스크롤을 따라오고, 창보다 길면 기둥 안에서 스크롤한다', () => {
    const body = rule('.annual-sim__form')
    expect(body).toMatch(/position:\s*sticky/)
    expect(body).toMatch(/max-block-size:/)
    expect(body).toMatch(/overflow-y:\s*auto/)
  })

  it('1100 이하에서는 한 단으로 접히고 따라오지 않는다', () => {
    const media = /@media \(max-width: 1100px\) \{([\s\S]*?)\n\}/.exec(CSS)?.[1] ?? ''
    expect(media).toMatch(/\.annual-sim\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    expect(media).toMatch(/\.annual-sim__form\s*\{[^}]*position:\s*static/)
  })
})

describe('결론 띠 — `DESIGN_SYSTEM §8.6` 🔒', () => {
  it('주 결론은 `display` 크기다', () => {
    expect(rule('.annual-sim__verdict-value')).toMatch(/font-size:\s*var\(--font-size-display\)/)
  })

  it('⚠️ 보조는 `display`가 아니다 — 주 결론 크기로 커지면 위반이다', () => {
    const body = rule('.annual-sim__verdict-sub-value')
    expect(body).not.toMatch(/--font-size-display/)
    expect(body).toMatch(/font-size:\s*var\(--font-size-h2\)/)
  })

  it('위험도 pill의 면은 중립이다 — 경고색은 글자에만 (`§2.3` · `§2.5 (b)`)', () => {
    const body = rule('.annual-sim__risk-pill')
    expect(body).not.toMatch(/warning|danger/)
  })
})

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
