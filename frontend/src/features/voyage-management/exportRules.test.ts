import { describe, expect, it } from 'vitest'
import {
  EXPORT_FORMATS,
  EXPORT_TYPES,
  EXPORT_TYPE_HINTS,
  EXPORT_TYPE_LABELS,
  exportQuery,
  fallbackFilename,
  initialExportForm,
  validateExport,
} from './exportRules'

/**
 * 운항 기록 내보내기 규칙 (#890 · `API_SPEC §8.1`).
 *
 * `PRD §5.1`이 MUST로 규정한 기능인데 **화면에서 도달할 수 없었다** — 서버·검사가
 * 완비돼 있고 프론트 호출부가 0건이었다(`grep -rn "/export" frontend/src` → 0).
 */

describe('선택지는 서버 정본의 사본이다 (#890)', () => {
  it('종류 3종 — services/data_export.py EXPORT_TYPES', () => {
    expect([...EXPORT_TYPES]).toEqual(['voyages', 'calculations', 'simulations'])
  })

  it('형식 2종 — EXPORT_FORMATS', () => {
    expect([...EXPORT_FORMATS]).toEqual(['csv', 'json'])
  })

  it('종류마다 한글 이름과 설명이 있다 — 영문 키를 그대로 보이지 않는다', () => {
    for (const type of EXPORT_TYPES) {
      expect(EXPORT_TYPE_LABELS[type]).toBeTruthy()
      expect(EXPORT_TYPE_HINTS[type]).toBeTruthy()
    }
  })
})

describe('검증 — 연도는 선택이다 (#890)', () => {
  it('기본 상태가 통과한다', () => {
    expect(validateExport(initialExportForm())).toEqual({})
  })

  it('연도가 비어 있어도 오류가 아니다 — §8.1의 year는 optional이다', () => {
    expect(validateExport({ type: 'voyages', year: '', format: 'csv' })).toEqual({})
  })

  it('연도가 네 자리가 아니면 막는다', () => {
    expect(validateExport({ type: 'voyages', year: '26', format: 'csv' }).year).toBeDefined()
    expect(validateExport({ type: 'voyages', year: '2026.5', format: 'csv' }).year).toBeDefined()
  })

  it('모르는 종류·형식을 화면에서 먼저 잡는다 — 서버 422를 기다리지 않는다', () => {
    expect(validateExport({ type: 'ships', year: '', format: 'csv' }).type).toBeDefined()
    expect(validateExport({ type: 'voyages', year: '', format: 'xlsx' }).format).toBeDefined()
  })
})

describe('쿼리 조립 — 빈 연도는 키 자체를 넣지 않는다 (#890)', () => {
  it('연도를 고르면 싣는다', () => {
    const query = new URLSearchParams(
      exportQuery({ type: 'calculations', year: '2026', format: 'json' }),
    )
    expect(query.get('type')).toBe('calculations')
    expect(query.get('year')).toBe('2026')
    expect(query.get('format')).toBe('json')
  })

  it('전체를 고르면 year 키가 없다 — `year=`를 보내면 서버가 422를 낸다', () => {
    const query = exportQuery({ type: 'voyages', year: '', format: 'csv' })
    expect(query).not.toContain('year')
    expect(new URLSearchParams(query).get('type')).toBe('voyages')
  })
})

describe('대체 파일명 — 이름 없는 파일을 내려보내지 않는다 (#890)', () => {
  it('연도가 있으면 이름에 넣는다', () => {
    expect(fallbackFilename({ type: 'voyages', year: '2026', format: 'csv' })).toBe(
      'voyages_2026.csv',
    )
  })

  it('전체면 종류와 형식만으로 만든다', () => {
    expect(fallbackFilename({ type: 'simulations', year: '', format: 'json' })).toBe(
      'simulations.json',
    )
  })
})
