import { formatPercent } from '../../display/format'
import { describe, expect, it } from 'vitest'
import {
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  sensitivityRows,
  stackSegments,
  INLINE_LABEL_MIN_PERCENT,
  showsInlineLabel,
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

/**
 * 구간 안 문자 표기 — `DESIGN_SYSTEM §10.2`.
 *
 * *"구간 폭 ≥ 8% 일 때만 내부에 `등급문자 nn%` 표기, 미만은 툴팁으로"*
 *
 * `AGENTS §4.6`에 따라 문구는 리터럴로 단언하지 않는다. 다만 **8% 임계와 자릿수는
 * 정본이 확정한 값**이므로 그대로 단언한다.
 */
describe('스택 바 구간 안 문자 — DESIGN_SYSTEM §10.2', () => {
  it('임계는 정본이 정한 8이다', () => {
    expect(INLINE_LABEL_MIN_PERCENT).toBe(8)
  })

  it('8% 경계를 포함한다 — 정확히 8%면 안에 넣는다', () => {
    // §10.2가 `≥`로 적었다. `>`로 잘못 쓰면 딱 8%인 구간만 조용히 빠진다.
    expect(showsInlineLabel(8)).toBe(true)
  })

  it('8% 바로 아래는 넣지 않는다', () => {
    expect(showsInlineLabel(7.9)).toBe(false)
    expect(showsInlineLabel(7.999)).toBe(false)
  })

  it('8% 바로 위는 넣는다', () => {
    expect(showsInlineLabel(8.001)).toBe(true)
    expect(showsInlineLabel(8.1)).toBe(true)
  })

  it('0% 구간은 넣지 않는다', () => {
    // 폭이 0이라 글자가 들어갈 자리가 없다. 구간 자체는 목록에서 빼지 않는다.
    expect(showsInlineLabel(0)).toBe(false)
  })

  it('합이 100%가 아니어도 구간 자신의 폭으로 판정한다', () => {
    /*
     * 서버 확률의 합은 반올림으로 99.9%나 100.1%가 되곤 한다. 100%로 정규화해
     * 판정하면 **화면에 그려진 폭과 근거가 어긋난다** — 폭이 곧 근거다.
     */
    const under = stackSegments({ A: '0.079', B: '0.30', C: '0.30', D: '0.20', E: '0.12' })
    const sum = under.reduce((acc, seg) => acc + seg.percent, 0)
    expect(sum).toBeLessThan(100)
    // 합이 99.9%여도 7.9%짜리 A는 여전히 8% 미만이다.
    expect(showsInlineLabel(under[0].percent)).toBe(false)

    const over = stackSegments({ A: '0.081', B: '0.30', C: '0.30', D: '0.20', E: '0.12' })
    expect(over.reduce((acc, seg) => acc + seg.percent, 0)).toBeGreaterThan(100)
    expect(showsInlineLabel(over[0].percent)).toBe(true)
  })

  it('구간 문자의 퍼센트는 소수 1자리다', () => {
    // §4.2 🔒 비율·확률 백분율 1자리. §10.2 예시의 정수는 형식 예시일 뿐이다.
    for (const seg of stackSegments({ A: '0.02', B: '0.15', C: '0.61', D: '0.20', E: '0.02' })) {
      expect(seg.label).toMatch(/^\d+\.\d%$/)
    }
  })

  it('바와 범례가 같은 포매터를 쓴다 — 반올림 경계에서 갈리지 않는다', () => {
    /*
     * 종전 `toPercent`는 `(Number(p) * 100).toFixed(1)`이었다. `'0.1235'`에서
     * `formatPercent`(ROUND_HALF_UP)와 답이 갈려, 같은 확률이 구간 안과 범례에서
     * 다른 숫자로 보일 수 있었다.
     */
    expect(toPercent('0.1235')).toBe(`${formatPercent('0.1235')}%`)
    expect(stackSegments({ A: '0.1235', B: '0', C: '0', D: '0', E: '0' })[0].label).toBe(
      toPercent('0.1235'),
    )
  })
})
