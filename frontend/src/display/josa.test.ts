import { describe, expect, it } from 'vitest'
import { finalConsonant, ro, withRo } from './josa'
import { STATUS_LABELS } from '../features/voyage-management/voyageRules'

describe('finalConsonant', () => {
  it('받침이 없으면 0이다', () => {
    expect(finalConsonant('완료')).toBe(0)
    expect(finalConsonant('가')).toBe(0)
  })

  it('받침이 있으면 0이 아니다', () => {
    expect(finalConsonant('확정')).not.toBe(0)
    expect(finalConsonant('중')).not.toBe(0)
  })

  it('한글이 아니면 null — 받침을 단정하지 않는다', () => {
    // `HFO`를 「에이치에프오」로 읽으면 받침이 없다. 사람마다 달라 알 수 없다.
    expect(finalConsonant('HFO')).toBeNull()
    expect(finalConsonant('2026')).toBeNull()
    expect(finalConsonant('')).toBeNull()
  })

  it('앞뒤 공백을 무시한다', () => {
    expect(finalConsonant('항해 완료 ')).toBe(0)
  })
})

describe('ro', () => {
  it('받침이 없으면 「로」', () => {
    expect(ro('항해 완료')).toBe('로')
  })

  it('받침이 있으면 「으로」', () => {
    expect(ro('실적 확정')).toBe('으로')
    expect(ro('작성 중')).toBe('으로')
  })

  it('ㄹ 받침은 「로」 — 유일한 예외다', () => {
    // 「서울로」이지 「서울으로」가 아니다. 이 예외를 빠뜨리면 지명·선박명에서 드러난다.
    expect(ro('서울')).toBe('로')
    expect(ro('물')).toBe('로')
  })

  it('한글이 아니면 「로」', () => {
    expect(ro('HFO')).toBe('로')
  })
})

describe('withRo — 항차 상태 7종 (#598)', () => {
  it('전환 버튼에 괄호가 나오지 않는다', () => {
    // 종전 화면은 `{STATUS_LABELS[to]}(으)로`라 「실적 확정(으)로」가 그대로 보였다.
    for (const label of Object.values(STATUS_LABELS)) {
      expect(withRo(label)).not.toContain('(')
      expect(withRo(label)).not.toContain(')')
    }
  })

  it('7종의 조사가 실제 받침을 따른다', () => {
    expect(withRo(STATUS_LABELS.DRAFT)).toBe('작성 중으로')
    expect(withRo(STATUS_LABELS.PLANNED)).toBe('계획 확정으로')
    expect(withRo(STATUS_LABELS.IN_PROGRESS)).toBe('항해 중으로')
    // 이 하나만 「로」다 — 한 문자열로 못 맞추는 이유다.
    expect(withRo(STATUS_LABELS.COMPLETED)).toBe('항해 완료로')
    expect(withRo(STATUS_LABELS.CONFIRMED)).toBe('실적 확정으로')
    expect(withRo(STATUS_LABELS.CANCELLED)).toBe('취소됨으로')
    expect(withRo(STATUS_LABELS.ARCHIVED)).toBe('보관됨으로')
  })

  it('7종이 모두 검사됐다', () => {
    // 상태가 늘면 위 목록이 낡는다. 개수를 함께 박아 조용히 빠지지 않게 한다.
    expect(Object.keys(STATUS_LABELS)).toHaveLength(7)
  })
})
