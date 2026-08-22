import { describe, expect, it } from 'vitest'
import { FUEL_TYPE_LABELS, fuelTypeLabel, fuelTypeOptionText } from './fuelTypes'

describe('FUEL_TYPE_LABELS (#598)', () => {
  it('DB_SCHEMA §3.2 값 표의 8종을 덮는다', () => {
    // 서버 마스터가 8행이다. 하나라도 빠지면 그 연료만 영문·코드로 보인다.
    expect(Object.keys(FUEL_TYPE_LABELS)).toEqual([
      'DIESEL_GAS_OIL',
      'LFO',
      'HFO',
      'LPG_PROPANE',
      'LPG_BUTANE',
      'LNG',
      'METHANOL',
      'ETHANOL',
    ])
  })

  it('영문 원문 표기를 그대로 쓰지 않는다', () => {
    // `display_name`(MEPC.364(79) 원문)은 정본 문구다. 그것을 옮겨 적으면 이 파일을
    // 둔 이유가 없어진다 (`AGENTS §4.6`).
    for (const label of Object.values(FUEL_TYPE_LABELS)) {
      expect(label).not.toMatch(/^[A-Za-z/ ]+$/)
    }
  })

  it('중유와 경질중유가 코드 병기로 갈린다', () => {
    // 두 이름이 서로를 포함해 라벨만으로는 겹쳐 보인다. 셀렉트에서 코드가 가른다.
    expect(fuelTypeOptionText('HFO')).toBe('중유 (HFO)')
    expect(fuelTypeOptionText('LFO')).toBe('경질중유 (LFO)')
  })
})

describe('fuelTypeLabel', () => {
  it('모르는 코드는 코드를 그대로 낸다', () => {
    // 서버에 연료가 늘었을 때 빈 칸·「기타」로 뭉개면 무엇을 고르는지 알 수 없고,
    // 표가 낡았다는 사실도 사라진다.
    expect(fuelTypeLabel('BIO_LNG')).toBe('BIO_LNG')
  })

  it('아는 코드는 한국어를 낸다', () => {
    expect(fuelTypeLabel('LNG')).toBe('액화천연가스')
  })
})

describe('fuelTypeOptionText', () => {
  it('모르는 코드는 코드를 두 번 적지 않는다', () => {
    expect(fuelTypeOptionText('BIO_LNG')).toBe('BIO_LNG')
  })
})
