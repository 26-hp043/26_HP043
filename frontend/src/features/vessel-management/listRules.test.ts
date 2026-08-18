import { describe, expect, it } from 'vitest'
import type { Vessel } from '../vessel-registration/types'
import {
  MISSING,
  blockedReasons,
  capacityCell,
  cellNumber,
  deleteConfirmMessage,
  shipTypeLabel,
} from './listRules'

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
