import { describe, expect, it } from 'vitest'
import {
  CONSUMER_TYPE_LABELS,
  PERIOD_TYPE_LABELS,
  formatRange,
  hasErrors,
  labelOf,
  toIso,
  toLocalInput,
  NO_VALUE_TEXT,
  quantityText,
  totalFuelTon,
  validateFuelDraft,
  validateDraft,
} from './periodRules'
import { DISPLAY_DIGITS } from '../../display/format'
import type { Period, PeriodDraft } from './types'

/**
 * not under way 화면 규칙 (`#370`).
 *
 * 가장 조용한 결함은 **시각대**다. 브라우저 로컬 시각을 그대로 ISO로 붙여 보내면
 * 9시간이 밀리고, 그 어긋남은 화면에 드러나지 않은 채 CII의 연도 귀속과 겹침 판정만
 * 바꾼다. 그래서 이 파일이 왕복을 고정한다.
 */

const PERIOD: Period = {
  id: 'p-1',
  vesselId: 'v-1',
  regulationYear: 2026,
  periodType: 'AT_ANCHOR',
  startedAt: '2026-08-10T14:00:00+00:00',
  endedAt: '2026-08-12T09:00:00+00:00',
  portName: '부산',
  distanceNm: 0,
  fuelUses: [
    { id: 'f-1', consumerType: 'OIL_FIRED_BOILER', fuelType: 'HFO', fuelTon: 12, cfUsed: 3.114 },
    { id: 'f-2', consumerType: 'AUX_ENGINE', fuelType: 'HFO', fuelTon: 4.5, cfUsed: 3.114 },
  ],
}

const DRAFT: PeriodDraft = {
  periodType: 'AT_ANCHOR',
  startedAt: '2026-08-10T14:00',
  endedAt: '2026-08-12T09:00',
  portName: '부산',
  distanceNm: '0',
  fuelUses: [{ consumerType: 'OIL_FIRED_BOILER', fuelType: 'HFO', fuelTon: '12' }],
}

describe('시각 변환', () => {
  it('로컬 입력을 UTC로 옮긴다 — Z를 붙여 보내면 시각대만큼 밀린다', () => {
    // 로컬 시각을 UTC로 옮긴 값이므로, 다시 로컬로 되돌리면 원래 문자열이어야 한다.
    expect(toLocalInput(toIso('2026-08-10T14:00'))).toBe('2026-08-10T14:00')
  })

  it('ISO를 datetime-local 형식으로 준다 — 초 이하는 버린다', () => {
    const local = toLocalInput('2026-08-10T14:00:00+00:00')
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  })
})

describe('표시', () => {
  it('진행 중을 「모름」으로 적지 않는다', () => {
    expect(formatRange({ ...PERIOD, endedAt: null })).toContain('진행 중')
  })

  it('끝난 구간은 두 시각을 모두 보여 준다', () => {
    expect(formatRange(PERIOD)).not.toContain('진행 중')
    expect(formatRange(PERIOD).split('~')).toHaveLength(2)
  })

  it('연료 합계를 소수 둘째 자리로 맞춘다', () => {
    expect(totalFuelTon(PERIOD)).toBe(16.5)
  })

  it('라벨이 없는 코드는 코드를 그대로 보여 준다', () => {
    // 서버가 새 값을 줘도 화면이 빈칸을 그리지 않는다.
    expect(labelOf('NEW_KIND', PERIOD_TYPE_LABELS)).toBe('NEW_KIND')
    // 아는 코드는 **코드가 아닌 말**로 바뀐다. 그 말이 무엇인지는 디자인 소관이다.
    expect(labelOf('AT_ANCHOR', PERIOD_TYPE_LABELS)).not.toBe('AT_ANCHOR')
    expect(labelOf('OIL_FIRED_BOILER', CONSUMER_TYPE_LABELS)).not.toBe('OIL_FIRED_BOILER')
  })
})

describe('입력 검증', () => {
  it('올바른 입력을 통과시킨다', () => {
    expect(hasErrors(validateDraft(DRAFT))).toBe(false)
  })

  it('종료가 시작보다 이르면 막는다', () => {
    const errors = validateDraft({ ...DRAFT, endedAt: '2026-08-09T00:00' })
    expect(errors.endedAt).toBeTruthy()
  })

  it('종료를 비우는 것은 정상이다 — 정박이 시작될 때는 끝을 모른다', () => {
    expect(hasErrors(validateDraft({ ...DRAFT, endedAt: null }))).toBe(false)
  })

  it('이동 거리 0을 막지 않는다 — 접안·묘박은 움직이지 않는다', () => {
    expect(hasErrors(validateDraft({ ...DRAFT, distanceNm: '0' }))).toBe(false)
  })

  it('음수 거리는 막는다', () => {
    expect(validateDraft({ ...DRAFT, distanceNm: '-1' }).distanceNm).toBeTruthy()
  })

  it('0톤 연료는 막는다 — 안 썼으면 줄을 지우면 된다', () => {
    const errors = validateDraft({
      ...DRAFT,
      fuelUses: [{ consumerType: 'AUX_ENGINE', fuelType: 'HFO', fuelTon: '0' }],
    })
    expect(errors.fuelUses).toBeTruthy()
  })

  it('연료가 하나도 없어도 통과시킨다 — 실적은 뒤에 붙일 수 있다', () => {
    expect(hasErrors(validateDraft({ ...DRAFT, fuelUses: [] }))).toBe(false)
  })

  it('같은 소비원·유종이 두 번이면 막는다', () => {
    const row = { consumerType: 'AUX_ENGINE', fuelType: 'HFO', fuelTon: '3' }
    expect(validateDraft({ ...DRAFT, fuelUses: [row, row] }).fuelUses).toBeTruthy()
  })

  it('소비원이 다르면 같은 유종을 두 번 넣을 수 있다', () => {
    // 보조기관과 보일러가 같은 기름을 쓰는 것은 정상이다.
    const draft = {
      ...DRAFT,
      fuelUses: [
        { consumerType: 'AUX_ENGINE', fuelType: 'HFO', fuelTon: '3' },
        { consumerType: 'OIL_FIRED_BOILER', fuelType: 'HFO', fuelTon: '12' },
      ],
    }
    expect(hasErrors(validateDraft(draft))).toBe(false)
  })

  it('겹침은 여기서 보지 않는다 — 다른 구간을 알아야 하고 그건 서버가 안다', () => {
    // 같은 시각의 초안이 두 번 들어와도 화면은 막지 않는다. 판정이 갈리면
    // 어느 쪽이 맞는지 판단할 근거가 없다.
    expect(hasErrors(validateDraft(DRAFT))).toBe(false)
    expect(hasErrors(validateDraft({ ...DRAFT }))).toBe(false)
  })
})

describe('quantityText — 표시 자릿수 (DESIGN_SYSTEM §4.2 🔒) (#572)', () => {
  const decimals = (t: string) => {
    const dot = t.indexOf('.')
    return dot === -1 ? 0 : t.length - dot - 1
  }

  it('연료는 소수 1자리다 — 원본 자릿수와 무관하게', () => {
    // 서버는 입력 정밀도 그대로 준다(12 · 4.5 · 3.456). 화면 자릿수는 §4.2가 정한다.
    for (const v of [12, 4.5, 3.456, 0]) {
      expect(decimals(quantityText(v, DISPLAY_DIGITS.fuelTon))).toBe(DISPLAY_DIGITS.fuelTon)
    }
  })

  it('거리는 소수 0자리다', () => {
    expect(quantityText(1234.6, DISPLAY_DIGITS.distanceNm)).toBe('1,235')
    expect(decimals(quantityText(12.4, DISPLAY_DIGITS.distanceNm))).toBe(0)
  })

  it('천단위 구분자를 넣는다 — 연료·거리는 GROUPED_FIELDS다', () => {
    expect(quantityText(12480.55, DISPLAY_DIGITS.fuelTon)).toBe('12,480.6')
  })

  it('반올림한다 — 잘라 내지 않는다', () => {
    expect(quantityText(4.55, DISPLAY_DIGITS.fuelTon)).toBe('4.6')
    expect(quantityText(999.5, DISPLAY_DIGITS.distanceNm)).toBe('1,000')
  })

  it('값이 없으면 포매터를 부르지 않는다 — 던지지 않고 빈 자리 표시를 낸다', () => {
    // 포매터는 십진 문자열이 아니면 던진다. 널을 그대로 넘기면 화면이 죽는다.
    expect(() => quantityText(null, DISPLAY_DIGITS.fuelTon)).not.toThrow()
    expect(quantityText(undefined, DISPLAY_DIGITS.fuelTon)).toBe(NO_VALUE_TEXT)
    expect(quantityText(Number.NaN, DISPLAY_DIGITS.fuelTon)).toBe(NO_VALUE_TEXT)
  })

  it('0은 빈 값이 아니다 — 안 넣은 것과 0은 다르다', () => {
    expect(quantityText(0, DISPLAY_DIGITS.distanceNm)).toBe('0')
  })

  it('지수 표기를 만들지 않는다 — String(1e-7)은 포매터가 던진다', () => {
    expect(quantityText(1e-7, DISPLAY_DIGITS.fuelTon)).toBe('0.0')
  })
})

describe('totalFuelTon — 반올림은 표시 시점에 한 번만 (#572)', () => {
  it('합계를 미리 자르지 않는다', () => {
    // 종전에는 `toFixed(2)`로 잘라 두어, 표시(1자리)에서 두 번 반올림됐다.
    const period: Period = {
      ...PERIOD,
      fuelUses: [
        { id: 'a', consumerType: 'AUX_ENGINE', fuelType: 'HFO', fuelTon: 16.449, cfUsed: 3.114 },
      ],
    }
    expect(quantityText(totalFuelTon(period), DISPLAY_DIGITS.fuelTon)).toBe('16.4')
  })

  it('기존 합계는 그대로다', () => {
    expect(totalFuelTon(PERIOD)).toBe(16.5)
  })
})

describe('validateFuelDraft — 나중에 더하는 연료 한 줄 (#638)', () => {
  const ok = { consumerType: 'AUX_ENGINE', fuelType: 'DIESEL_GAS_OIL', fuelTon: '4.5' }

  it('정상 입력은 통과한다', () => {
    expect(validateFuelDraft(ok)).toBeNull()
  })

  it('0톤은 오타로 본다 — 안 썼으면 줄을 넣지 않으면 된다', () => {
    expect(validateFuelDraft({ ...ok, fuelTon: '0' })).toContain('0보다 커야')
  })

  it('빈 값·숫자가 아닌 값도 거부한다', () => {
    expect(validateFuelDraft({ ...ok, fuelTon: '' })).not.toBeNull()
    expect(validateFuelDraft({ ...ok, fuelTon: 'abc' })).not.toBeNull()
  })

  it('선택지가 비어 있으면 거부한다 — 화면이 기본값을 지어내지 않는다', () => {
    expect(validateFuelDraft({ ...ok, consumerType: '' })).toContain('선택해')
    expect(validateFuelDraft({ ...ok, fuelType: '' })).toContain('선택해')
  })

  it('validateDraft와 같은 문구를 쓴다 — 같은 값에 다른 규칙으로 읽히면 안 된다', () => {
    // 구간 생성 폼과 나중 추가 폼이 같은 값을 받는데 거부 문구가 다르면
    // 사용자는 규칙이 다르다고 읽는다.
    const inForm = validateDraft({
      periodType: 'IN_PORT',
      startedAt: '2026-08-01T00:00',
      endedAt: null,
      portName: null,
      distanceNm: '0',
      fuelUses: [{ ...ok, fuelTon: '0' }],
    }).fuelUses
    expect(validateFuelDraft({ ...ok, fuelTon: '0' })).toBe(inForm)
  })

  it('중복은 보지 않는다 — 서버가 409로 판정한다 (API_SPEC §2.13)', () => {
    // 이미 저장된 구간의 연료와 대조해야 하는데 화면은 그것을 알 수 없다.
    // 흉내 내면 두 판정이 갈리고, 갈린 쪽이 맞다고 믿을 근거가 없다.
    expect(validateFuelDraft(ok)).toBeNull()
  })
})
