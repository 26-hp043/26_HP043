import { describe, expect, it } from 'vitest'
import {
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  selectedYear,
  sensitivityRows,
  stackSegments,
  toPercent,
} from './annualRules'
import type { MonteCarloBlock } from './types'

const P = { A: '0.0200', B: '0.2800', C: '0.5500', D: '0.1300', E: '0.0200' }

describe('P(D∪E) — PRD §12.5', () => {
  it('P(D) + P(E)로 계산한다', () => {
    expect(probabilityOfDorE(P)).toBeCloseTo(0.15, 6)
  })

  it('1 − 목표 달성 확률로 계산하지 않는다', () => {
    // `PRD §12.5` — 여사건 관계는 **목표가 C일 때만** 성립한다. 목표가 B인 화면에서
    // `1 − success`를 쓰면 C 확률까지 위험으로 세어 값이 부풀려진다.
    const successForTargetB = 0.02 + 0.28
    expect(probabilityOfDorE(P)).not.toBeCloseTo(1 - successForTargetB, 3)
  })
})

describe('위험도 표기 — DESIGN_SYSTEM §2.5 (a)', () => {
  it('20% 미만은 경고 기호를 붙이지 않는다', () => {
    const flag = riskFlag(0.15)
    expect(flag.tone).toBe('muted')
    expect(flag.text).not.toContain('⚠')
  })

  it('20% 이상 40% 미만은 Warning이다', () => {
    expect(riskFlag(0.28).tone).toBe('warning')
    expect(riskFlag(0.2).tone).toBe('warning')
  })

  it('40% 이상은 Danger다', () => {
    expect(riskFlag(0.4).tone).toBe('danger')
    expect(riskFlag(0.47).tone).toBe('danger')
  })

  it('경계값이 위쪽 구간에 속한다', () => {
    // 20%·40% 정확히 걸린 값을 아래 구간으로 넣으면 임계의 뜻이 「초과」가 된다.
    expect(riskFlag(0.199).tone).toBe('muted')
    expect(riskFlag(0.399).tone).toBe('warning')
  })
})

describe('확률 스택 바 — DESIGN_SYSTEM §10.2', () => {
  it('A~E 다섯 구간을 항상 같은 순서로 낸다', () => {
    expect(stackSegments(P).map((s) => s.rating)).toEqual(['A', 'B', 'C', 'D', 'E'])
  })

  it('폭이 0인 구간도 빼지 않는다', () => {
    // 두 실행을 나란히 놓고 비교할 수 있어야 한다.
    const zeroE = { ...P, E: '0.0000' }
    expect(stackSegments(zeroE)).toHaveLength(5)
    expect(stackSegments(zeroE)[4].percent).toBe(0)
  })

  it('폭의 합이 100이다', () => {
    const total = stackSegments(P).reduce((sum, s) => sum + s.percent, 0)
    expect(total).toBeCloseTo(100, 6)
  })
})

describe('민감도 행', () => {
  it('응답에 없는 변수는 표에 넣지 않는다', () => {
    // 빈 행을 남기면 「값이 0」으로 읽힌다.
    const rows = sensitivityRows({
      interaction_note: 'n',
      speed_minus_1kn: { projected_cii: '4.85', rating_change: 'C→B' },
    })
    expect(rows).toHaveLength(1)
    expect(rows[0].label).toContain('속력')
  })

  it('interaction_note를 행으로 오인하지 않는다', () => {
    expect(sensitivityRows({ interaction_note: 'n' })).toEqual([])
  })
})

describe('표시 변환', () => {
  it('확률을 백분율 1자리로 쓴다', () => {
    expect(toPercent('0.3000')).toBe('30.0%')
  })

  it('재현 정보에 seed와 생성기가 함께 들어간다', () => {
    // 이 줄이 없으면 「이 seed로 다시 실행」을 확인할 방법이 없다.
    const mc = {
      rng_metadata: {
        seed_entropy: '0x3039',
        bit_generator: 'PCG64DXSM',
        numpy_version: '2.1.0',
        python_version: '3.12',
        platform: 'Linux',
      },
      runs: 5000,
    } as MonteCarloBlock
    const line = reproducibilityLine(mc)
    expect(line).toContain('0x3039')
    expect(line).toContain('PCG64DXSM')
    expect(line).toContain('5000')
  })
})

describe('selectedYear — 기준연도 선택 유지 규칙 (#558)', () => {
  const YEARS = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]

  it('고른 해가 새 목록에도 있으면 유지한다', () => {
    // 선박을 바꿀 때마다 되돌아가면 사용자가 방금 고른 값을 잃는다.
    expect(selectedYear('2024', YEARS)).toBe('2024')
  })

  it('없으면 가장 최근 해를 고른다', () => {
    // 「올해 남은 항차로 목표를 맞출 수 있는가」를 보는 화면이라(PRD §12)
    // 과거 연도를 기본으로 두면 첫 화면이 의미를 잃는다.
    expect(selectedYear('2019', YEARS)).toBe('2030')
    expect(selectedYear('', YEARS)).toBe('2030')
  })

  it('목록이 비면 값을 지어내지 않는다', () => {
    // 종전 고정값(2026)이 정확히 그 형태였고 사용자는 다른 해를 볼 수 없었다.
    expect(selectedYear('2026', [])).toBe('')
    expect(selectedYear('', [])).toBe('')
  })

  it('문자열 비교로 놓치지 않는다 — 목록은 숫자다', () => {
    expect(selectedYear('2026', [2026])).toBe('2026')
  })
})
