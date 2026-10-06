import { describe, expect, it } from 'vitest'
import { addFixed, compareFixed, shareOfMax, subtractFixed } from './decimal'
import { formatDecimalString } from './format'

/**
 * 표시 자릿수에서의 십진 사칙 (`#739` · `#820` · 검사 신설 `#2124`).
 *
 * 이 모듈이 지키는 것은 **화면의 두 값을 눈으로 더하고 뺀 결과와 같다**는 것이다. 그래서
 * 기대값은 「표시값끼리 손으로 계산한 값」으로 적는다 — 원본끼리 계산한 값이 아니다.
 */
describe('subtractFixed — 표시값의 차', () => {
  it('원본이 아니라 표시값으로 뺀다', () => {
    // 원본의 차는 111.54 - 106.15 = 5.39 → 5.4. 그런데 화면에는 111.5 · 106.2(반올림)가
    // 보이므로 5.3이어야 한다 — 모듈 주석의 사례 그대로다.
    expect(formatDecimalString('111.54', 1)).toBe('111.5')
    expect(formatDecimalString('106.15', 1)).toBe('106.2')
    expect(subtractFixed('111.54', '106.15', 1)).toBe('5.3')
  })

  it('음수 결과에 부호를 붙이고 자릿수를 지킨다', () => {
    expect(subtractFixed('1.0', '1.5', 1)).toBe('-0.5')
    expect(subtractFixed('0.001', '0.010', 3)).toBe('-0.009')
  })

  it('같은 표시값이면 0이다 — 숨은 자리의 차를 드러내지 않는다', () => {
    expect(subtractFixed('4.9821', '4.9824', 3)).toBe('0.000')
  })

  it('digits=0이면 소수점을 붙이지 않는다', () => {
    expect(subtractFixed('1200', '80', 0)).toBe('1120')
  })
})

describe('addFixed — 표시값의 합', () => {
  it('부동소수 오차가 끼지 않는다', () => {
    // 0.1 + 0.2 === 0.30000000000000004
    expect(0.1 + 0.2).not.toBe(0.3)
    expect(addFixed('0.1', '0.2', 1)).toBe('0.3')
  })

  it('자리올림이 정수부로 번진다', () => {
    expect(addFixed('9.95', '0.05', 2)).toBe('10.00')
  })

  it('부호가 다른 두 값을 더한다', () => {
    expect(addFixed('-1.5', '0.5', 1)).toBe('-1.0')
    expect(addFixed('-0.5', '0.5', 1)).toBe('0.0')
  })

  it('안전 정수 범위를 넘는 값도 자리를 잃지 않는다', () => {
    // 2^53 + 1 = 9007199254740993 — `number`로는 담지 못한다.
    expect(addFixed('9007199254740992', '1', 0)).toBe('9007199254740993')
  })

  it('뺄셈과 서로 되돌린다', () => {
    const sum = addFixed('106.2', '5.3', 1)
    expect(subtractFixed(sum, '5.3', 1)).toBe('106.2')
  })
})

describe('compareFixed — 표시값의 대소', () => {
  it('작으면 음수, 같으면 0, 크면 양수다', () => {
    expect(compareFixed('0.39', '0.40', 2)).toBeLessThan(0)
    expect(compareFixed('0.40', '0.40', 2)).toBe(0)
    expect(compareFixed('0.41', '0.40', 2)).toBeGreaterThan(0)
  })

  it('표시 자릿수에서 같으면 같다고 답한다', () => {
    // 4자리에서는 둘 다 0.4000이다.
    expect(compareFixed('0.39996', '0.4', 4)).toBe(0)
  })

  it('임계 판정이 화면의 숫자와 같은 답을 낸다 (#820)', () => {
    // `Number`로 더하면 0.39999999999999997이라 `>= 0.4`가 거짓이 된다.
    expect(0.35 + 0.05 >= 0.4).toBe(false)
    expect(compareFixed(addFixed('0.3500', '0.0500', 4), '0.4', 4)).toBe(0)
  })

  it('음수끼리는 절댓값이 큰 쪽이 작다', () => {
    expect(compareFixed('-2.0', '-1.0', 1)).toBeLessThan(0)
    expect(compareFixed('-0.1', '0.0', 1)).toBeLessThan(0)
  })

  it('인자를 바꾸면 부호가 뒤집힌다', () => {
    expect(Math.sign(compareFixed('1.2', '3.4', 1))).toBe(-Math.sign(compareFixed('3.4', '1.2', 1)))
  })
})

describe('shareOfMax — 막대 길이 비율 (#2202)', () => {
  it('최댓값을 100으로 두고 나머지를 표시값 기준 비율로 낸다', () => {
    expect(shareOfMax(['100.0', '50.0', '25.0'], 1)).toEqual([100, 50, 25])
  })

  it('표시 자릿수로 맞춘 뒤 나눈다 — 막대 옆 글자와 같은 숫자에서 나온다', () => {
    // 6.6144 → 6.614 · 6.6136 → 6.614 (3자리) → 둘 다 100
    expect(shareOfMax(['6.6144', '6.6136'], 3)).toEqual([100, 100])
  })

  it('0에서 시작한다 — 차이가 작으면 막대도 비슷하다(축을 자르지 않는다)', () => {
    const [a, b] = shareOfMax(['6.614', '6.500'], 3)
    expect(a).toBe(100)
    expect(b).toBeGreaterThan(98)
  })

  it('최댓값이 0이면 전부 0이고, 음수는 0으로 둔다', () => {
    expect(shareOfMax(['0', '0.0'], 1)).toEqual([0, 0])
    expect(shareOfMax(['-5.0', '10.0'], 1)).toEqual([0, 100])
  })
})
