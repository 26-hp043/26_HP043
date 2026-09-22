import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 위험도(`risk_level`) 색 — `DESIGN_SYSTEM §2.5 (b)` 🔒 (2026-09-22 확정).
 *
 * | 단계 | 라벨 색 | 아이콘 색 |
 * |---|---|---|
 * | LOW · MEDIUM | 본문색 | 없음 |
 * | HIGH | `--color-warning-text` | `--color-warning-text` |
 * | CRITICAL | `--color-danger-text` | `--color-warning-text` |
 *
 * ## 왜 세 화면을 한 파일에서 보는가
 *
 * 규칙이 없던 동안 **기능②만 HIGH·CRITICAL·아이콘을 모두 Danger로** 두었다. 화면별
 * 테스트는 자기 화면만 보므로 이런 갈라짐을 잡지 못한다. 한 표를 세 화면에 대조한다.
 */
const SCREENS = [
  {
    // 기능① 항차 CII · 기능③ 연간 등급 — 결론 띠 공용 부품 (#1711)
    name: '결론 띠 (기능① · ③)',
    file: 'src/components/VerdictStrip.css',
    high: '.verdict-strip__risk-value--high',
    critical: '.verdict-strip__risk-value--critical',
    icon: '.verdict-strip__risk-icon',
  },
  {
    name: '기능② 실시간 CII',
    file: 'src/features/realtime-cii/RealtimeCiiView.css',
    high: '.rt__axis-facts .rt__risk--high',
    critical: '.rt__axis-facts .rt__risk--critical',
    icon: '.rt__risk-icon',
  },
  {
    name: '시나리오 비교',
    file: 'src/features/scenario-comparison/ScenarioComparison.css',
    high: '.scenario-table__risk-value--high',
    critical: '.scenario-table__risk-value--critical',
    icon: '.scenario-table__risk-icon',
  },
] as const

/** 선택자 목록에 `selector`가 **그 자체로** 들어 있는 규칙의 `color` 값. */
function colorOf(css: string, selector: string): string | null {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, '')
  for (const [, selectors, body] of plain.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const list = selectors.split(',').map((s) => s.trim().replace(/\s+/g, ' '))
    if (!list.includes(selector)) continue
    const color = /(?:^|;)\s*color:\s*([^;]+)/.exec(body)
    if (color) return color[1].trim()
  }
  return null
}

describe('위험도 색 — DESIGN_SYSTEM §2.5 (b)', () => {
  it.each(SCREENS)('$name — HIGH는 Warning, CRITICAL은 Danger, 아이콘은 Warning 하나', (s) => {
    const css = readFileSync(join(process.cwd(), s.file), 'utf-8')
    expect(colorOf(css, s.high), s.high).toBe('var(--color-warning-text)')
    expect(colorOf(css, s.critical), s.critical).toBe('var(--color-danger-text)')
    expect(colorOf(css, s.icon), s.icon).toBe('var(--color-warning-text)')
  })
})
