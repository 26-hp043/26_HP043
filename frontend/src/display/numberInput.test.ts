import { describe, expect, it } from 'vitest'
import { formatGrouped } from './format'
import { readNumberInput } from './numberInput'

/**
 * 숫자 입력 한 칸의 해석 (#2124).
 *
 * 종전에는 `Number('1,000')`이 `NaN`이라 「0보다 커야 합니다」가 나갔다. 화면이 값을
 * 천 단위 쉼표로 보여 주므로(`DESIGN_SYSTEM §4.2`) 사용자는 그 꼴로 옮겨 적는다.
 */
describe('readNumberInput', () => {
  it('화면이 적어 준 꼴을 그대로 받는다', () => {
    // 포매터가 낸 문자열을 되읽으면 원래 값이다 — 「보이는 대로 옮겨 적는다」의 왕복.
    expect(readNumberInput(formatGrouped('12480', 0))).toBe(12480)
    expect(readNumberInput(formatGrouped('1234567.5', 1))).toBe(1234567.5)
    expect(readNumberInput('1,000')).toBe(1000)
    expect(readNumberInput('-1,000.25')).toBe(-1000.25)
  })

  it('전각 숫자·기호를 반각으로 읽는다', () => {
    expect(readNumberInput('１２４８０')).toBe(12480)
    expect(readNumberInput('１３．５')).toBe(13.5)
    expect(readNumberInput('１，０００')).toBe(1000)
  })

  it('쉼표가 없는 평범한 입력은 종전과 같다', () => {
    expect(readNumberInput('2800')).toBe(2800)
    expect(readNumberInput(' 13.5 ')).toBe(13.5)
    expect(readNumberInput('0')).toBe(0)
    expect(readNumberInput('-3')).toBe(-3)
  })

  it('세 자리씩 끊기지 않은 쉼표는 읽지 않는다 — 소수점 쉼표를 추측하지 않는다', () => {
    // `12,5`를 125로 읽으면 열 배 틀린 값이 조용히 저장된다.
    for (const raw of ['12,5', '1,00', '1,2345', ',100', '1,,000', '1,000,', '1.5,000', '1,000.5,0']) {
      expect(readNumberInput(raw), raw).toBeNaN()
    }
  })

  it('비어 있음 · 읽을 수 없음 · 읽음이 서로 다른 답이다', () => {
    expect(readNumberInput('')).toBeNull()
    expect(readNumberInput('   ')).toBeNull()
    expect(readNumberInput('십일천')).toBeNaN()
    expect(readNumberInput('12abc')).toBeNaN()
    // 유한하지 않은 값도 「읽을 수 없음」이다.
    expect(readNumberInput('Infinity')).toBeNaN()
  })
})
