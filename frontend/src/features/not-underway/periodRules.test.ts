import { describe, expect, it } from 'vitest'
import {
  CONSUMER_TYPE_LABELS,
  PERIOD_TYPE_LABELS,
  formatRange,
  hasErrors,
  labelOf,
  toIso,
  toLocalInput,
  totalFuelTon,
  validateDraft,
} from './periodRules'
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
    expect(labelOf('AT_ANCHOR', PERIOD_TYPE_LABELS)).toBe('묘박')
    expect(labelOf('OIL_FIRED_BOILER', CONSUMER_TYPE_LABELS)).toBe('보일러')
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
