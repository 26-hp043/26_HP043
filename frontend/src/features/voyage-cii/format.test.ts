import { describe, expect, it } from 'vitest'
import { DISPLAY_DIGITS, formatDecimalString } from './format'

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

  it('PRD §9.3 표시 자릿수를 노출한다', () => {
    expect(DISPLAY_DIGITS).toEqual({ cii: 3, fuelTon: 2, co2Ton: 2, distanceNm: 1 })
  })
})
