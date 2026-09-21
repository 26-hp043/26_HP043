import { describe, expect, it } from 'vitest'
import { SCREEN_BY_ID } from '../../screens'
import type { RegulationYearRow } from './referenceApiProvider'
import {
  FUEL_NO_HISTORY_NOTICE,
  REGULATION_PARAMETERS_ANCHOR,
  appliedBaselineText,
  regulationParametersPath,
} from './referenceRules'

/**
 * 「규제 기준값」 절의 순수 규칙 (`#1516`).
 *
 * 링크 경로는 **설정 경로 + 앵커**여야 한다 — 새 화면이 아니라 절이므로(`screens.test.ts`가
 * `NAV_ORDER`를 잠근다). 대시보드 한 줄은 그 연도의 활성 행이 없으면 **없다** — 값을
 * 지어내지 않는다.
 */

function year(overrides: Partial<RegulationYearRow> = {}): RegulationYearRow {
  return {
    year: 2026,
    zFactorPercent: '11.0',
    effectiveFrom: '2026-01-01',
    sourceRef: 'MEPC.400(83)',
    version: '2025-q2',
    isActive: true,
    ...overrides,
  }
}

describe('절 링크 경로', () => {
  it('설정 화면 경로에 앵커를 붙인다 — 화면 ID를 늘리지 않는다', () => {
    const path = regulationParametersPath()
    expect(path.startsWith(SCREEN_BY_ID.SETTINGS.path)).toBe(true)
    expect(path.endsWith(`#${REGULATION_PARAMETERS_ANCHOR}`)).toBe(true)
  })
})

describe('대시보드 「적용 기준」 한 줄', () => {
  it('그 연도의 활성 행에서 출처와 감축률을 문자열 그대로 잇는다', () => {
    const text = appliedBaselineText([year({ zFactorPercent: '11.0' })], 2026)
    expect(text).not.toBeNull()
    expect(text).toContain('MEPC.400(83)')
    expect(text).toContain('2026')
    // 반올림·자릿수 가공 없이 서버 문자열이 그대로 들어간다.
    expect(text).toContain('11.0%')
  })

  it('그 연도의 행이 없으면 null이다 — 다른 연도의 값을 붙여 보이지 않는다', () => {
    expect(appliedBaselineText([year({ year: 2025 })], 2026)).toBeNull()
    expect(appliedBaselineText([], 2026)).toBeNull()
  })

  it('이행 행만 있으면 null이다 — 계산은 활성 행만 본다', () => {
    expect(appliedBaselineText([year({ isActive: false })], 2026)).toBeNull()
  })

  it('활성 행과 이행 행이 섞여 있으면 활성 행을 고른다', () => {
    const rows = [year({ isActive: false, zFactorPercent: '9.00' }), year({ zFactorPercent: '11.0' })]
    expect(appliedBaselineText(rows, 2026)).toContain('11.0%')
    expect(appliedBaselineText(rows, 2026)).not.toContain('9.00')
  })
})

describe('연료 이력 없음 안내', () => {
  it('「없음」의 종류를 말한다 — 이력이 없는 것이지 값이 없는 것이 아니다', () => {
    // 문구 리터럴이 아니라 성질을 본다(`AGENTS §4.6`) — 갱신 방식을 언급하고 빈 문자열이 아니다.
    expect(FUEL_NO_HISTORY_NOTICE.length).toBeGreaterThan(0)
    expect(FUEL_NO_HISTORY_NOTICE).toContain('갱신')
  })
})
