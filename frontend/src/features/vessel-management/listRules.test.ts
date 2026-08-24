import { describe, expect, it } from 'vitest'
import type { Vessel } from '../vessel-registration/types'
import {
  MISSING,
  SORT_KEYS,
  blockedReasons,
  capacityCell,
  cellNumber,
  dailyFuelCell,
  deleteConfirmMessage,
  referenceSpeedCell,
  shipTypeLabel,
  sortVessels,
  specChecklist,
  specProgress,
} from './listRules'
import { formatCapacity } from '../../display/format'

/**
 * #510 — 선박 목록 표시 규칙.
 *
 * 핵심은 **「무엇이 비어 있어 무엇이 안 되는가」를 목록에서 바로 보이게 하는 것**이다.
 * `#511`(항로 비교가 데모 선박에서 실패한다)의 원인이 정확히 이 정보의 부재였다 —
 * 사용자는 선박 상세를 열어 「제원」이 전부 `—`인 것을 보고 나서야 이유를 알았다.
 */

function vessel(overrides: Partial<Vessel> = {}): Vessel {
  return {
    id: '00000000-0000-4000-8000-000000000001',
    imo_number: '0000001',
    name: '샘플 벌크선',
    ship_type: 'BULK_CARRIER',
    gross_tonnage: 30000,
    deadweight: 50000,
    default_fuel_type: null,
    reference_speed_kn: 14,
    reference_daily_foc_ton: 20,
    is_cii_applicable_hint: true,
    underway_state: null,
    detail_status: null,
    current_lat: null,
    current_lon: null,
    position_updated_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

describe('cellNumber — 없는 값을 빈 칸으로 두지 않는다', () => {
  it('null은 —로 적는다', () => {
    expect(cellNumber(null)).toBe(MISSING)
  })

  it('숫자는 천단위 구분자를 넣는다', () => {
    expect(cellNumber(50000)).toBe('50,000')
  })
})

describe('shipTypeLabel', () => {
  it('아는 선종은 한국어 라벨로 보인다', () => {
    expect(shipTypeLabel('BULK_CARRIER')).toBe('벌크선')
  })

  it('모르는 코드는 감추지 않고 그대로 보인다', () => {
    expect(shipTypeLabel('NO_SUCH_TYPE')).toBe('NO_SUCH_TYPE')
  })
})

describe('capacityCell — 그 선종이 실제로 쓰는 축만 보인다', () => {
  it('DWT 기반 선종은 DWT를 보인다', () => {
    expect(capacityCell(vessel({ ship_type: 'BULK_CARRIER' }))).toEqual({
      label: 'DWT',
      value: '50,000',
    })
  })

  it('GT 기반 선종은 GT를 보인다', () => {
    expect(capacityCell(vessel({ ship_type: 'RO_RO_PASSENGER' }))).toEqual({
      label: 'GT',
      value: '30,000',
    })
  })

  it('DESIGN_SYSTEM §4.2 — 소수를 0자리로 고정한다 (#633)', () => {
    // 종전에는 `toLocaleString`이라 `50,000`과 `6,405.77`이 섞였다.
    expect(capacityCell(vessel({ ship_type: 'BULK_CARRIER', deadweight: 6405.77 })).value).toBe(
      '6,406',
    )
  })

  it('선박 상세와 같은 문자열을 낸다 — 화면마다 다르게 포맷하지 않는다 (#633)', () => {
    // **이 이슈의 본체다.** 목록은 포맷을 거치고 상세는 서버 문자열을 그대로 그려
    // 같은 값이 `6,405.77`과 `6405.77`로 갈렸다. 두 화면이 같은 함수를 쓰는지 본다.
    for (const dwt of [50000, 9520, 6405.77]) {
      expect(capacityCell(vessel({ ship_type: 'BULK_CARRIER', deadweight: dwt })).value).toBe(
        formatCapacity(dwt),
      )
    }
  })

  it('선종을 모르면 축도 지어내지 않고 둘 다 보인다', () => {
    expect(capacityCell(vessel({ ship_type: 'NO_SUCH_TYPE' })).label).toBe('GT / DWT')
  })
})

describe('blockedReasons — 이 배로 지금 할 수 없는 것', () => {
  it('제원과 연료 모델이 모두 있으면 막힌 것이 없다', () => {
    expect(blockedReasons(vessel())).toEqual([])
  })

  it('DWT 기반 선종에 DWT가 없으면 등급 산출 불가를 적는다', () => {
    const reasons = blockedReasons(vessel({ deadweight: null }))
    expect(reasons.some((r) => r.includes('재화중량톤수(DWT) 없음'))).toBe(true)
  })

  it('GT 기반 선종에 GT가 없으면 등급 산출 불가를 적는다', () => {
    const reasons = blockedReasons(
      vessel({ ship_type: 'RO_RO_PASSENGER', gross_tonnage: null }),
    )
    expect(reasons.some((r) => r.includes('총톤수(GT) 없음'))).toBe(true)
  })

  it('DWT 기반 선종은 GT가 비어도 등급 산출을 막지 않는다 (PRD §3.3.3)', () => {
    const reasons = blockedReasons(vessel({ gross_tonnage: null }))
    expect(reasons.some((r) => r.includes('총톤수(GT) 없음'))).toBe(false)
  })

  it('연료 모델이 비면 무엇이 빠졌는지 이름을 적는다 (#511의 원인)', () => {
    // `PRD §11.4` ⑵는 두 값이 **함께** 있어야 성립한다
    // (`calc/annual_simulation.py:509`가 같은 판단을 한다).
    const reasons = blockedReasons(
      vessel({ reference_speed_kn: null, reference_daily_foc_ton: null }),
    )
    const fuel = reasons.find((r) => r.includes('항로 비교'))
    expect(fuel).toContain('기준속도')
    expect(fuel).toContain('기준 일일 연료소모량')
  })

  it('하나만 있어도 나머지 하나를 짚는다 — 「있으니 되겠지」로 읽히면 안 된다', () => {
    const reasons = blockedReasons(vessel({ reference_daily_foc_ton: null }))
    const fuel = reasons.find((r) => r.includes('항로 비교'))
    expect(fuel).toContain('기준 일일 연료소모량')
    expect(fuel).not.toContain('기준속도 ·')
  })

  it('데모 선박의 실제 상태를 그대로 재현한다 — 4척 모두 일일 연료가 비어 있다', () => {
    // `src/cii_platform/db/demo_seed.py`의 `reference_daily_foc_ton`이 전부 None이다.
    const demo = vessel({ reference_speed_kn: 16.5, reference_daily_foc_ton: null })
    expect(blockedReasons(demo).some((r) => r.includes('항로 비교'))).toBe(true)
  })
})

describe('deleteConfirmMessage — soft delete임을 밝힌다', () => {
  it('되돌릴 수 있다는 사실을 적는다 (#52 완료 기준)', () => {
    const message = deleteConfirmMessage(vessel())
    expect(message).toContain('샘플 벌크선')
    expect(message).toContain('0000001')
    expect(message).toContain('이력은 보존')
    expect(message).toContain('다시 등록')
  })

  it('「영구 삭제」로 적지 않는다', () => {
    expect(deleteConfirmMessage(vessel())).not.toContain('영구')
  })
})

/**
 * 제원 완성도 (#719).
 *
 * ## 왜 `blockedReasons`와 따로 보나
 *
 * 둘은 **같은 판정에서 나와야 한다.** 완성도를 따로 세면 규칙이 두 벌이 되고,
 * 갈렸을 때 화면은 멀쩡해 보인다 — 「3개 중 3개」인데 아래에 경고가 붙어 있는
 * 모양이 되고, 어느 쪽이 맞는지는 코드를 읽어야 안다.
 *
 * 그래서 여기서는 **두 결과가 서로 어긋나지 않는지**를 함께 단언한다.
 */
describe('specChecklist — 채워야 할 것 세 가지', () => {
  it('다 채워져 있으면 3/3이고 막힌 것도 없다', () => {
    expect(specProgress(vessel())).toEqual({ filled: 3, total: 3 })
    expect(blockedReasons(vessel())).toEqual([])
  })

  it('DWT 기반 선종은 DWT를 센다 — GT가 비어도 완성도가 깎이지 않는다', () => {
    expect(specProgress(vessel({ gross_tonnage: null }))).toEqual({ filled: 3, total: 3 })
    expect(specProgress(vessel({ deadweight: null }))).toEqual({ filled: 2, total: 3 })
  })

  it('GT 기반 선종은 GT를 센다', () => {
    const roro = { ship_type: 'RO_RO_PASSENGER' }
    expect(specProgress(vessel({ ...roro, gross_tonnage: null }))).toEqual({
      filled: 2,
      total: 3,
    })
    expect(specProgress(vessel({ ...roro, deadweight: null }))).toEqual({
      filled: 3,
      total: 3,
    })
  })

  it('선종을 모르면 용량은 세지 않는다 — 어느 축이 필요한지도 모른다', () => {
    const unknown = vessel({ ship_type: 'NOT_A_SHIP_TYPE' })
    // 분모에서 빠진다. 「2개 중 2개」이지 「3개 중 2개」가 아니다.
    expect(specProgress(unknown)).toEqual({ filled: 2, total: 2 })
    // 그리고 용량 미비를 이유로 적지도 않는다 — 종전 동작과 같다.
    expect(blockedReasons(unknown).some((r) => r.includes('없음 — CII'))).toBe(false)
  })

  it('데모 선박의 실제 상태 — 일일 연료만 비어 2/3다', () => {
    expect(specProgress(vessel({ reference_daily_foc_ton: null }))).toEqual({
      filled: 2,
      total: 3,
    })
  })

  it('완성도와 막힌 이유가 어긋나지 않는다', () => {
    const cases = [
      vessel(),
      vessel({ deadweight: null }),
      vessel({ reference_speed_kn: null }),
      vessel({ reference_daily_foc_ton: null }),
      vessel({ deadweight: null, reference_speed_kn: null, reference_daily_foc_ton: null }),
    ]
    for (const one of cases) {
      const { filled, total } = specProgress(one)
      // 다 채웠으면 막힌 것이 없고, 하나라도 비면 이유가 반드시 있다.
      expect(blockedReasons(one).length === 0).toBe(filled === total)
    }
  })

  it('빠진 항목의 이름이 곧 사용자가 채울 칸의 이름이다', () => {
    const missing = specChecklist(vessel({ reference_daily_foc_ton: null })).filter(
      (item) => !item.filled,
    )
    expect(missing.map((item) => item.label)).toEqual(['기준 일일 연료소모량'])
  })
})

describe('sortVessels — 원본을 바꾸지 않고 순서만 만든다', () => {
  const full = vessel({ id: 'a', name: '가나호' })
  const oneGap = vessel({ id: 'b', name: '나나호', reference_speed_kn: null })
  const twoGaps = vessel({
    id: 'c',
    name: '다나호',
    reference_speed_kn: null,
    reference_daily_foc_ton: null,
  })

  it('기본 정렬은 덜 채워진 배를 위로 올린다', () => {
    const order = sortVessels([full, oneGap, twoGaps], 'gaps').map((v) => v.id)
    expect(order).toEqual(['c', 'b', 'a'])
  })

  it('원본 배열을 건드리지 않는다 — 수정 중인 행이 정렬로 흔들리면 안 된다', () => {
    const input = [full, oneGap, twoGaps]
    sortVessels(input, 'name')
    expect(input.map((v) => v.id)).toEqual(['a', 'b', 'c'])
  })

  it('용량순에서 값이 없는 배는 끝으로 간다 — 0으로 치면 가장 작은 배가 된다', () => {
    const noCapacity = vessel({ id: 'z', name: '하나호', deadweight: null })
    const small = vessel({ id: 's', name: '사나호', deadweight: 1000 })
    const order = sortVessels([noCapacity, small], 'capacity').map((v) => v.id)
    expect(order).toEqual(['s', 'z'])
  })

  it('모든 키가 결정적이다 — 같은 입력이면 같은 순서다', () => {
    for (const key of SORT_KEYS) {
      const once = sortVessels([twoGaps, full, oneGap], key).map((v) => v.id)
      const twice = sortVessels([oneGap, twoGaps, full], key).map((v) => v.id)
      expect(twice).toEqual(once)
    }
  })
})

/**
 * 제원 값 셀 (#719).
 *
 * 완성도 막대(「2/3」)를 값 두 칸으로 바꾸면서 생긴 자리다. 막대는 **몇 개**만 말하고
 * *무엇이* 빠졌는지는 아래 경고 문장을 읽어야 했다.
 *
 * 자릿수·단위를 여기서 리터럴로 적지 않는다(`#164`) — `display/format`이 소유한다.
 * 그래서 단언도 「`§4.2`가 정한 자리수로 나오는가」를 본다.
 */
describe('제원 값 셀 — 없으면 null, 있으면 §4.2 표기', () => {
  it('기준속도는 소수 1자리에 단위를 붙인다', () => {
    expect(referenceSpeedCell(vessel({ reference_speed_kn: 12.8 }))).toBe('12.8 kn')
    // 정수로 들어와도 자릿수를 고정한다 — 목록에서 열이 흔들리지 않는다.
    expect(referenceSpeedCell(vessel({ reference_speed_kn: 14 }))).toBe('14.0 kn')
  })

  it('일일 연료는 천 단위를 끊는다 — `GROUPED_FIELDS`', () => {
    expect(dailyFuelCell(vessel({ reference_daily_foc_ton: 20 }))).toBe('20.0 t')
    expect(dailyFuelCell(vessel({ reference_daily_foc_ton: 1234.5 }))).toBe('1,234.5 t')
  })

  it('없으면 문자열을 지어내지 않고 null을 낸다 — 표기는 화면의 몫', () => {
    expect(referenceSpeedCell(vessel({ reference_speed_kn: null }))).toBeNull()
    expect(dailyFuelCell(vessel({ reference_daily_foc_ton: null }))).toBeNull()
  })

  it('값이 있는 항목은 완성도에서도 채워진 것으로 센다 — 두 표현이 어긋나지 않는다', () => {
    const one = vessel({ reference_daily_foc_ton: null })
    expect(dailyFuelCell(one)).toBeNull()
    expect(specProgress(one)).toEqual({ filled: 2, total: 3 })
  })
})
