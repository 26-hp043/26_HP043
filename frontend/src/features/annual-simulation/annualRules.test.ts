import { formatPercent } from '../../display/format'
import { describe, expect, it } from 'vitest'
import {
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  sensitivityRows,
  stackSegments,
  INLINE_LABEL_MIN_PERCENT,
  toPercent,
  toSignedPercent,
} from './annualRules'
import type { MonteCarloBlock } from './types'

const P = { A: '0.0200', B: '0.2800', C: '0.5500', D: '0.1300', E: '0.0200' }

describe('P(D∪E) — PRD §12.5', () => {
  it('P(D) + P(E)로 계산한다', () => {
    // `#820` — 십진 문자열이다. `toBeCloseTo`로 보면 float 오차가 가려진다.
    expect(probabilityOfDorE(P)).toBe('0.1500')
  })

  it('1 − 목표 달성 확률로 계산하지 않는다', () => {
    // `PRD §12.5` — 여사건 관계는 **목표가 C일 때만** 성립한다. 목표가 B인 화면에서
    // `1 − success`를 쓰면 C 확률까지 위험으로 세어 값이 부풀려진다.
    expect(probabilityOfDorE(P)).not.toBe('0.7000')
  })

  it.each([
    // 화면에 같은 숫자가 뜨는데 D·E 배분만 다른 조합들 (`#820`).
    // `Number` 합은 각각 0.39999999999999997 · 0.19999999999999998이 된다.
    [{ D: '0.3500', E: '0.0500' }, '0.4000'],
    [{ D: '0.4000', E: '0.0000' }, '0.4000'],
    [{ D: '0.2900', E: '0.1100' }, '0.4000'],
    [{ D: '0.0400', E: '0.3600' }, '0.4000'],
    [{ D: '0.1800', E: '0.0200' }, '0.2000'],
    [{ D: '0.2000', E: '0.0000' }, '0.2000'],
  ])('배분이 달라도 합은 같다: %j → %s', (split, expected) => {
    expect(probabilityOfDorE({ A: '0', B: '0', C: '0', ...split })).toBe(expected)
  })
})

describe('위험도 표기 — DESIGN_SYSTEM §2.5 (a)', () => {
  it('20% 미만은 경고 기호를 붙이지 않는다', () => {
    const flag = riskFlag('0.1500')
    expect(flag.tone).toBe('muted')
    expect(flag.text).not.toContain('⚠')
  })

  it('20% 이상 40% 미만은 Warning이다', () => {
    expect(riskFlag('0.2800').tone).toBe('warning')
    expect(riskFlag('0.2000').tone).toBe('warning')
  })

  it('40% 이상은 Danger다', () => {
    expect(riskFlag('0.4000').tone).toBe('danger')
    expect(riskFlag('0.4700').tone).toBe('danger')
  })

  it('경계값이 위쪽 구간에 속한다', () => {
    // 20%·40% 정확히 걸린 값을 아래 구간으로 넣으면 임계의 뜻이 「초과」가 된다.
    expect(riskFlag('0.1990').tone).toBe('muted')
    expect(riskFlag('0.3990').tone).toBe('warning')
  })

  it.each([
    // `#820` — **같은 숫자가 화면에 뜨는데 색이 갈리던** 조합. `Number` 합은
    // 0.39999999999999997이라 종전에는 warning으로 칠해졌다.
    [{ D: '0.3500', E: '0.0500' }, 'danger'],
    [{ D: '0.4000', E: '0.0000' }, 'danger'],
    [{ D: '0.2900', E: '0.1100' }, 'danger'],
    [{ D: '0.0400', E: '0.3600' }, 'danger'],
    // 같은 20.0%인데 ⚠가 붙었다 안 붙었다 하던 조합.
    [{ D: '0.1800', E: '0.0200' }, 'warning'],
    [{ D: '0.2000', E: '0.0000' }, 'warning'],
  ])('배분이 달라도 같은 색·같은 아이콘: %j → %s', (split, tone) => {
    const flag = riskFlag(probabilityOfDorE({ A: '0', B: '0', C: '0', ...split }))

    expect(flag.tone).toBe(tone)
    // `DESIGN_SYSTEM §14` — 색맹 사용자가 의존하는 **색 외 보조 채널**이다.
    // 같은 값에서 나타났다 사라지면 색과 아이콘 두 채널이 함께 무너진다.
    expect(flag.text).toContain('⚠')
  })

  it('표기 반올림이 toPercent와 같다 — ROUND_HALF_UP', () => {
    // `#820` ⑵ — 종전에는 `toFixed`라 `'0.1235'`가 여기서는 12.3%,
    // `toPercent`에서는 12.4%였다. **바로 아래 함수가 이미 고친 결함이
    // 형제에 남아 있었다.**
    expect(riskFlag('0.1235').text).toContain('12.4%')
    expect(riskFlag('0.1235').text).toBe(`P(D/E) ${toPercent('0.1235')}`)
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
/** C 구간에만 확률을 세운 스택. 판정은 구간 자신의 값만 보므로 나머지는 0이면 된다. */
function segmentC(value: string) {
  return stackSegments({ A: '0', B: '0', C: value, D: '0', E: '0' })[2]
}

describe('스택 바 구간 안 문자 — DESIGN_SYSTEM §10.2', () => {
  it('임계는 정본이 정한 8이다', () => {
    expect(INLINE_LABEL_MIN_PERCENT).toBe(8)
  })

  it('8% 경계를 포함한다 — 정확히 8%면 안에 넣는다', () => {
    // §10.2가 `≥`로 적었다. `>`로 잘못 쓰면 딱 8%인 구간만 조용히 빠진다.
    expect(segmentC('0.0800').inline).toBe(true)
  })

  it('8% 바로 아래는 넣지 않는다', () => {
    expect(segmentC('0.0790').inline).toBe(false)
    expect(segmentC('0.0700').inline).toBe(false)
  })

  it('8% 바로 위는 넣는다', () => {
    expect(segmentC('0.0810').inline).toBe(true)
    expect(segmentC('0.0900').inline).toBe(true)
  })

  it('0% 구간은 넣지 않는다', () => {
    // 폭이 0이라 글자가 들어갈 자리가 없다. 구간 자체는 목록에서 빼지 않는다.
    expect(segmentC('0').inline).toBe(false)
  })

  it('합이 100%가 아니어도 구간 자신의 폭으로 판정한다', () => {
    /*
     * 서버 확률의 합은 반올림으로 99.9%나 100.1%가 되곤 한다. 100%로 정규화해
     * 판정하면 **화면에 쓰인 숫자와 근거가 어긋난다** — 그 숫자가 곧 근거다 (#846).
     */
    const under = stackSegments({ A: '0.079', B: '0.30', C: '0.30', D: '0.20', E: '0.12' })
    const sum = under.reduce((acc, seg) => acc + seg.percent, 0)
    expect(sum).toBeLessThan(100)
    // 합이 99.9%여도 7.9%짜리 A는 여전히 8% 미만이다.
    expect(under[0].inline).toBe(false)

    const over = stackSegments({ A: '0.081', B: '0.30', C: '0.30', D: '0.20', E: '0.12' })
    expect(over.reduce((acc, seg) => acc + seg.percent, 0)).toBeGreaterThan(100)
    expect(over[0].inline).toBe(true)
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

/*
 * 「달성 확률 변화」가 백분율로 나간다 (#822).
 *
 * 종전에는 서버 값(`+0.12`)을 그대로 그렸다. 같은 화면 위쪽 지표가 `30.0%`라
 * 사용자는 **0.12%p로 읽지만 실제는 12%p** — 100배 오독이다.
 */
describe('sensitivityRows의 「달성 확률 변화」 (#822)', () => {
  /*
   * 종전에는 컴포넌트 안 삼항 연산자가 **서버 원값을 그대로** 그렸다 — 검사가 닿지
   * 않는 자리였다. 표시 결정을 이 함수로 옮겨 DOM 없이 고정한다.
   */
  it('백분율로 환산해 부호를 유지한다', () => {
    const rows = sensitivityRows({
      interaction_note: 'n',
      speed_minus_1kn: {
        projected_cii: '4.85',
        rating_change: 'C→B',
        target_probability_change: '+0.12',
      },
    })

    expect(rows[0].probabilityChange).toBe('+12.0%')
    // 서버 원값이 화면으로 새지 않는다 — 그것이 100배 오독의 원인이었다.
    expect(rows[0].probabilityChange).not.toBe('+0.12')
  })

  it('악화 방향의 부호를 잃지 않는다', () => {
    const rows = sensitivityRows({
      interaction_note: 'n',
      speed_plus_1kn: {
        projected_cii: '5.20',
        rating_change: 'B→C',
        target_probability_change: '-0.08',
      },
    })

    expect(rows[0].probabilityChange).toBe('-8.0%')
  })

  it('확률을 함께 내지 않는 지렛대는 「—」다', () => {
    // `API_SPEC §6.1` — 확률 변화는 일부 지렛대만 낸다. 나머지는 등급 변화만 보인다.
    const rows = sensitivityRows({
      interaction_note: 'n',
      distance_minus_5pct: { projected_cii: '4.90', rating_change: 'C→C' },
    })

    expect(rows[0].probabilityChange).toBe('—')
  })

  it('변화가 0이면 「—」가 아니다 — 0은 값이다', () => {
    const rows = sensitivityRows({
      interaction_note: 'n',
      fuel_minus_10pct: {
        projected_cii: '4.90',
        rating_change: 'C→C',
        target_probability_change: '+0.0000',
      },
    })

    expect(rows[0].probabilityChange).toBe('+0.0%')
  })
})

describe('toSignedPercent (#822)', () => {
  it('양수에 `+`를 유지한다 — 개선과 악화가 구분돼야 한다', () => {
    // `formatPercent`는 앞의 `+`를 떼어 버린다. 그래서 별도 함수가 필요하다.
    expect(formatPercent('+0.12')).toBe('12.0')
    expect(toSignedPercent('+0.12')).toBe('+12.0%')
  })

  it('음수 부호를 잃지 않는다', () => {
    expect(toSignedPercent('-0.08')).toBe('-8.0%')
  })

  it('0은 `+0.0%`다 — 서버의 `_signed`가 0에 `+`를 붙인다', () => {
    expect(toSignedPercent('+0.0000')).toBe('+0.0%')
  })

  it('반올림이 `formatPercent`와 같다 — ROUND_HALF_UP', () => {
    // `toFixed`였다면 `12.3%`. 정본은 `ROUND_HALF_UP`이라 `12.4%`다.
    expect(toSignedPercent('+0.1235')).toBe(`+${formatPercent('0.1235')}%`)
    expect(toSignedPercent('+0.1235')).toBe('+12.4%')
  })

  it('앞뒤 공백을 견딘다', () => {
    expect(toSignedPercent(' +0.12 ')).toBe('+12.0%')
  })
})

/**
 * #846 — 구간 안 문자 판정이 **표시된 숫자**를 따른다.
 *
 * `percent`는 float 곱셈(`0.0795 * 100 = 7.949999…`)이고 `label`은 ROUND_HALF_UP
 * (`8.0%`)이라, 둘이 경계에서 갈렸다. 종전에는 **화면에 「8.0%」라고 쓰인 칸이
 * 문자를 못 받고 툴팁으로 밀렸다.**
 */
describe('스택 바 — 표시된 숫자로 판정한다 (#846)', () => {
  it('8.0%로 표시되는 확률 전 범위가 안쪽 배치다', () => {
    // 서버가 보내는 4자리 확률 중 8.0%로 **반올림되는** 것들이다.
    for (const value of ['0.0795', '0.0796', '0.0797', '0.0798', '0.0799', '0.0800']) {
      const seg = segmentC(value)
      expect(seg.label).toBe('8.0%')
      expect(seg.inline).toBe(true)
    }
  })

  it('7.9%로 표시되면 안쪽이 아니다 — 임계를 낮추는 것이 아니다', () => {
    const seg = segmentC('0.0794')
    expect(seg.label).toBe('7.9%')
    expect(seg.inline).toBe(false)
  })

  it('그리는 폭은 그대로 float다 — 판정만 표시값을 쓴다', () => {
    // 폭까지 반올림하면 칸들의 합이 100%에서 더 벌어진다.
    const seg = segmentC('0.0795')
    expect(seg.percent).toBeCloseTo(7.95, 6)
    expect(seg.inline).toBe(true)
  })
})
