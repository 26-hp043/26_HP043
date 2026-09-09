import { describe, expect, it } from 'vitest'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  GROUPED_FIELDS,
  formatCapacity,
  formatDecimalString,
  formatGrouped,
  formatPercent,
  toDecimalInput,
} from './format'

describe('formatDecimalString', () => {
  it('지정한 소수 자릿수로 표시한다', () => {
    expect(formatDecimalString('4.982400', 3)).toBe('4.982')
    expect(formatDecimalString('5.045066', 3)).toBe('5.045')
  })

  it('ROUND_HALF_UP으로 반올림한다', () => {
    expect(formatDecimalString('4.9825', 3)).toBe('4.983')
    expect(formatDecimalString('4.9824', 3)).toBe('4.982')
    // 정확히 5는 올린다
    expect(formatDecimalString('0.125', 2)).toBe('0.13')
  })

  it('자릿수가 모자라면 0으로 채운다', () => {
    expect(formatDecimalString('80', 2)).toBe('80.00')
    expect(formatDecimalString('4.98', 6)).toBe('4.980000')
  })

  it('자리올림이 정수부로 번져도 처리한다', () => {
    expect(formatDecimalString('9.999', 2)).toBe('10.00')
    expect(formatDecimalString('9.9999', 0)).toBe('10')
    expect(formatDecimalString('0.99', 1)).toBe('1.0')
  })

  it('digits=0이면 소수점을 붙이지 않는다', () => {
    expect(formatDecimalString('1000.0', 0)).toBe('1000')
    expect(formatDecimalString('1000.5', 0)).toBe('1001')
  })

  it('부호를 보존하되 -0을 만들지 않는다', () => {
    expect(formatDecimalString('-0.365370', 3)).toBe('-0.365')
    expect(formatDecimalString('-0.0004', 3)).toBe('0.000')
  })

  it('앞자리 0을 정리한다', () => {
    expect(formatDecimalString('007.5', 1)).toBe('7.5')
    expect(formatDecimalString('0.5', 1)).toBe('0.5')
  })

  it('원본 정밀도를 float으로 훼손하지 않는다', () => {
    // 0.1 + 0.2 !== 0.3 류의 오차가 끼어들 여지가 없어야 한다
    expect(formatDecimalString('0.1', 20)).toBe('0.10000000000000000000')
    // JS number로 표현 불가능한 자릿수도 그대로 다룬다
    expect(formatDecimalString('4.98240000000000000001', 20)).toBe(
      '4.98240000000000000001',
    )
  })

  it('십진 문자열이 아니면 거부한다', () => {
    expect(() => formatDecimalString('abc', 2)).toThrow(TypeError)
    expect(() => formatDecimalString('1e5', 2)).toThrow(TypeError)
    expect(() => formatDecimalString('', 2)).toThrow(TypeError)
  })

  it('digits가 0 이상의 정수가 아니면 거부한다', () => {
    expect(() => formatDecimalString('1.0', -1)).toThrow(RangeError)
    expect(() => formatDecimalString('1.0', 1.5)).toThrow(RangeError)
  })

  it('DESIGN_SYSTEM §4.1 · §4.2 표시 자릿수를 노출한다', () => {
    // §4.2 소수 자릿수 표(🔒) + §4.1 CII 3자리.
    // PRD §9.3과 3건 상충하나 AGENTS §3.2.2상 DESIGN_SYSTEM 소관이다.
    expect(DISPLAY_DIGITS).toEqual({
      cii: 3,
      fuelTon: 1,
      co2Ton: 1,
      distanceNm: 0,
      durationHours: 1,
      days: 0,
      speedKn: 1,
      capacity: 0,
      percent: 1,
    })
  })

  it('ROUND_HALF_UP — 정확히 절반은 올린다', () => {
    // #164 체크리스트 B의 대조표
    expect(formatDecimalString('1.24', 1)).toBe('1.2')
    expect(formatDecimalString('1.25', 1)).toBe('1.3')
  })

  it('안전 정수 범위를 넘는 문자열도 정밀도를 보존한다', () => {
    expect(formatDecimalString('12345678901234567890.5', 1)).toBe(
      '12345678901234567890.5',
    )
  })
})

describe('formatGrouped', () => {
  it('천 단위 미만에는 구분자를 넣지 않는다', () => {
    expect(formatGrouped('80.0', 1)).toBe('80.0')
    expect(formatGrouped('999', 0)).toBe('999')
  })

  it('천 단위 이상 정수에 구분자를 넣는다', () => {
    expect(formatGrouped('12480', 0)).toBe('12,480')
    expect(formatGrouped('38215', 0)).toBe('38,215')
  })

  it('정수부에만 넣는다', () => {
    expect(formatGrouped('1000.0', 1)).toBe('1,000.0')
    // 소수부가 세 자리를 넘어도 구분자가 끼지 않아야 한다
    expect(formatGrouped('1000.123456', 6)).toBe('1,000.123456')
  })

  it('안전 정수 범위를 넘는 문자열에도 적용한다', () => {
    expect(formatGrouped('12345678901234567890.5', 1)).toBe(
      '12,345,678,901,234,567,890.5',
    )
  })

  it('자릿수 반올림을 거친 뒤 구분자를 넣는다', () => {
    // 999.95 → 1000.0 → 1,000.0 : 자리올림으로 자릿수가 늘어난 뒤에 끊어야 한다
    expect(formatGrouped('999.95', 1)).toBe('1,000.0')
  })

  it('음수 부호를 보존한다', () => {
    expect(formatGrouped('-12480', 0)).toBe('-12,480')
  })

  it('CII·비율·확률은 대상이 아니다', () => {
    // §4.2 — 명시적으로 제외하지 않으면 구현에서 일괄 적용될 여지가 있다
    expect(GROUPED_FIELDS).toEqual(['fuelTon', 'co2Ton', 'distanceNm', 'capacity'])
    expect(GROUPED_FIELDS).not.toContain('cii')
    expect(GROUPED_FIELDS).not.toContain('percent')
    expect(GROUPED_FIELDS).not.toContain('days')
    expect(GROUPED_FIELDS).not.toContain('speedKn')
  })
})

describe('formatCapacity (#633)', () => {
  it('DESIGN_SYSTEM §4.2 — 0자리 + 천단위 구분자', () => {
    expect(formatCapacity(50000)).toBe('50,000')
    expect(formatCapacity(25000)).toBe('25,000')
    expect(formatCapacity(9520)).toBe('9,520')
  })

  it('소수를 0자리로 고정한다 — 값에 따라 자릿수가 달라지지 않는다', () => {
    // 종전에는 `toLocaleString`이라 `50,000`과 `6,405.77`이 섞였다.
    expect(formatCapacity(6405.77)).toBe('6,406')
    expect(formatCapacity('6405.77')).toBe('6,406')
  })

  it('숫자로 오든 문자열로 오든 같은 값을 낸다', () => {
    // 선박 목록은 number(`§2.1`), 선박 상세는 문자열로 받는다.
    expect(formatCapacity(50000)).toBe(formatCapacity('50000.00'))
  })

  it('없으면 null — 「없음」 표기는 화면이 정한다', () => {
    // 목록은 `—`, 등록 결과는 「미입력」이다. 여기서 정하면 그 차이를 지운다.
    expect(formatCapacity(null)).toBeNull()
  })
})

describe('formatPercent', () => {
  it('소수 비율을 백분율 1자리로 바꾼다', () => {
    // §4.2 — §4.1의 3자리를 적용하면 0.988이 되어 의미가 전달되지 않는다
    expect(formatPercent('0.98758')).toBe('98.8')
    expect(formatPercent('0.072')).toBe('7.2')
  })

  it('곱셈을 거치지 않아 부동소수점 오차가 끼지 않는다', () => {
    // Number('0.98758') * 100 === 98.75800000000001
    expect(formatPercent('0.98758', 12)).toBe('98.758000000000')
  })

  it('소수 자릿수가 2 미만이어도 처리한다', () => {
    expect(formatPercent('1')).toBe('100.0')
    expect(formatPercent('0.5')).toBe('50.0')
    expect(formatPercent('0')).toBe('0.0')
  })

  it('% 기호를 붙이지 않는다 — 단위 부착은 호출부 책임', () => {
    expect(formatPercent('0.98758')).not.toContain('%')
  })

  it('십진 문자열이 아니면 거부한다', () => {
    expect(() => formatPercent('abc')).toThrow(TypeError)
    expect(() => formatPercent('1e-2')).toThrow(TypeError)
  })
})

describe('DISPLAY_UNITS', () => {
  // DESIGN_SYSTEM §4.2 「단위 표기 🔒」를 고정한다. 값이 바뀌면 정본 개정이
  // 선행되어야 하므로, 여기서 깨지는 것이 의도된 알림이다 (#164).
  it('DESIGN_SYSTEM §4.2 확정값과 일치한다', () => {
    expect(DISPLAY_UNITS.fuel).toBe('t')
    expect(DISPLAY_UNITS.co2).toBe('tCO₂')
    expect(DISPLAY_UNITS.distance).toBe('nm')
    expect(DISPLAY_UNITS.duration).toBe('h')
    expect(DISPLAY_UNITS.speed).toBe('kn')
    expect(DISPLAY_UNITS.day).toBe('일')
  })

  it('일수는 소수를 갖지 않는다 — 소수 구간은 시간이 소유한다', () => {
    // `§4.2` (#592). 규정이 없던 동안 화면이 `231.64 일`을 내고 있었다.
    // 0.1일 = 2.4시간이라 「며칠 남았나」에 의미를 더하지 않으며, 그 정밀도가
    // 필요하면 단위가 `h`로 바뀌어야 한다.
    expect(DISPLAY_DIGITS.days).toBe(0)
    expect(formatDecimalString('231.64', DISPLAY_DIGITS.days)).toBe('232')
    expect(formatDecimalString('133.36', DISPLAY_DIGITS.days)).toBe('133')
  })

  it('연료와 CO₂를 서로 다른 문자열로 구분한다', () => {
    // 둘 다 질량(t)이지만 같은 화면에 나란히 놓인다. 같으면 무엇의 질량인지
    // 읽을 수 없다 — 이 구분이 tCO₂를 택한 이유다.
    expect(DISPLAY_UNITS.co2).not.toBe(DISPLAY_UNITS.fuel)
  })

  it('연료 단위로 ton을 쓰지 않는다', () => {
    // short ton(907kg)·long ton(1,016kg)과 표기가 겹쳐 규제 맥락에서 모호하다.
    expect(DISPLAY_UNITS.fuel).not.toBe('ton')
  })

  it('CII 단위는 여기 없다 — 선종 capacity 축에서 파생된다 (§4.1)', () => {
    expect(DISPLAY_UNITS).not.toHaveProperty('cii')
  })
})


describe('toDecimalInput (#872)', () => {
  it('지수 표기가 되는 극소값을 십진 문자열로 옮긴다', () => {
    // `String(5e-7)`은 `"5e-7"`이고, 그 문자열이 포매터에 들어가면 던진다.
    expect(String(5e-7)).toBe('5e-7')
    expect(toDecimalInput(5e-7)).toBe('0.000000')
  })

  it('포매터가 그 결과를 받는다 — 화면이 죽지 않는다', () => {
    // 이 조합이 실시간 CII 화면을 통째로 죽였다. 계획 거리가 큰 항차의 출항 직후
    // 진행률이 이 범위에 들어간다.
    expect(() => formatPercent(String(5e-7))).toThrow(TypeError)
    expect(formatPercent(toDecimalInput(5e-7))).toBe('0.0')
  })

  it('평범한 값은 그대로 통과한다 — 표시값이 바뀌지 않는다', () => {
    expect(formatPercent(toDecimalInput(0.5))).toBe(formatPercent('0.5'))
    expect(formatGrouped(toDecimalInput(1234.5), 2)).toBe(formatGrouped('1234.5', 2))
    expect(formatDecimalString(toDecimalInput(12.75), 1)).toBe(formatDecimalString('12.75', 1))
  })

  it('반올림은 포매터가 한 번만 한다 — 6자리는 그보다 넉넉하다', () => {
    // 다리에서 자르는 자리가 표시 자릿수보다 깊어야 이중 반올림이 생기지 않는다.
    expect(toDecimalInput(0.9999999)).toBe('1.000000')
    expect(formatDecimalString(toDecimalInput(4.9825), 3)).toBe('4.983')
  })

  it('유한하지 않으면 던진다 — 조용히 「없음」으로 바꾸지 않는다', () => {
    // 포매터의 기존 규율과 같다 (`#823` 판정: 조용한 폴백은 틀린 값을 숨긴다).
    expect(() => toDecimalInput(Number.NaN)).toThrow(TypeError)
    expect(() => toDecimalInput(Number.POSITIVE_INFINITY)).toThrow(TypeError)
  })

  it('1e21 이상은 여전히 포매터가 던진다 — 그 경계는 입력 하한·상한 문제다', () => {
    // `toFixed`도 그 위에서는 지수 표기를 낸다. `#860`이 서버에서 막는다.
    expect(toDecimalInput(1e21)).toBe('1e+21')
    expect(() => formatGrouped(toDecimalInput(1e21), 2)).toThrow(TypeError)
  })
})
