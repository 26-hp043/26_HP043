import { describe, expect, it } from 'vitest'
import { eulReul, eunNeun, finalConsonant, ro, withEulReul, withEunNeun, withRo } from './josa'
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

describe('eulReul — 목적격 조사 (2026-09-11 디자인 확정 B)', () => {
  it('받침이 있으면 「을」, 없으면 「를」', () => {
    expect(withEulReul('선박 목록')).toBe('선박 목록을')
    expect(withEulReul('규제연도 목록')).toBe('규제연도 목록을')
    expect(withEulReul('항차')).toBe('항차를')
    expect(withEulReul('선박 정보')).toBe('선박 정보를')
  })

  it('ㄹ 받침도 「을」이다 — 「로」와 달리 예외가 없다', () => {
    expect(eulReul('선대 현황 자료')).toBe('를')
    expect(eulReul('실시간 값')).toBe('을')
    expect(eulReul('규칙')).toBe('을')
    expect(eulReul('연료 일')).toBe('을')
  })

  it('한글로 끝나지 않으면 「를」', () => {
    expect(eulReul('CSV')).toBe('를')
    expect(eulReul('HFO')).toBe('를')
  })
})

describe('eunNeun — 주격 조사 (#1369)', () => {
  it('받침이 있으면 은, 없으면 는이다', () => {
    expect(eunNeun('선명')).toBe('은')
    expect(eunNeun('속력')).toBe('은')
    expect(eunNeun('연료')).toBe('는')
    expect(eunNeun('거리')).toBe('는')
  })

  it('끝의 괄호 설명은 건너뛰고 앞 낱말로 고른다', () => {
    // 서버(`api/validation_messages.py`의 `_TRAILING_PAREN`)와 같은 규칙이다.
    // 이것이 없으면 아래 라벨들에서 화면과 서버가 다른 조사를 낸다.
    expect(withEunNeun('총톤수(GT)')).toBe('총톤수(GT)는')
    expect(withEunNeun('재화중량톤수(DWT)')).toBe('재화중량톤수(DWT)는')
    expect(withEunNeun('방형계수(CB)')).toBe('방형계수(CB)는')
    expect(withEunNeun('시작 시각(부터)')).toBe('시작 시각(부터)은')
    expect(withEunNeun('난수 시드(seed)')).toBe('난수 시드(seed)는')
  })

  it('한글로 끝나지 않으면 는이다 — 괄호를 화면에 내보내지 않는다', () => {
    // 2026-09-11 디자인 확정 B. `eulReul`·`ro`와 같은 판단이다.
    expect(eunNeun('IMO')).toBe('는')
    expect(eunNeun('2026')).toBe('는')
  })
})

describe('화면이 조사를 박아 쓰지 않는다 (#1369)', () => {
  it('검증 문구에 「은(는)」 병기가 남아 있지 않다', async () => {
    // 종전에는 여덟 자리가 `${label}은(는) …`을 그대로 적었다. 서버는 받침을 계산해
    // 하나만 쓰므로, 같은 오류에 두 가지 문구가 나갔다.
    const { readFileSync, readdirSync, statSync } = await import('node:fs')
    const { join } = await import('node:path')
    const { fileURLToPath } = await import('node:url')

    const root = fileURLToPath(new URL('..', import.meta.url))
    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((entry) => {
        const full = join(dir, entry)
        if (statSync(full).isDirectory()) return walk(full)
        return /\.tsx?$/.test(entry) && !/\.test\./.test(entry) ? [full] : []
      })

    const offenders = walk(root).filter((file) => {
      if (file.endsWith('josa.ts')) return false // 규칙을 설명하는 주석이 있다
      return readFileSync(file, 'utf-8').includes('은(는)')
    })

    expect(offenders).toEqual([])
  })
})
