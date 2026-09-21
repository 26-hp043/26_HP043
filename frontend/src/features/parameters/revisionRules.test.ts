import { describe, expect, it } from 'vitest'
import {
  PARAMETER_KINDS,
  actorLabel,
  canCommit,
  revisionSummary,
  type ParameterImportResult,
  type ParameterRevisionEvent,
} from './revisionRules'

/**
 * 규제 기준값 개정 적재 규칙 (`#1517`).
 *
 * 가장 중요한 것은 **확정 조건이 항차 CSV와 반대라는 것**이다 — `§7.5`는 전부 아니면 전무라
 * 오류가 한 건이라도 있는 검증 결과로 확정을 열면 아무것도 안 들어간다.
 */

function result(overrides: Partial<ParameterImportResult> = {}): ParameterImportResult {
  return {
    kind: 'regulation_years',
    importedCount: 3,
    replacedCount: 1,
    errors: [],
    dryRun: true,
    ...overrides,
  }
}

describe('canCommit', () => {
  it('검증을 통과하고 오류가 0건일 때만 연다', () => {
    expect(canCommit(result())).toBe(true)
  })

  it('들어갈 행이 있어도 오류가 한 건이면 열지 않는다 — 전부 아니면 전무', () => {
    expect(
      canCommit(result({ errors: [{ row: 4, field: 'c', message: '숫자가 아닙니다.' }] })),
    ).toBe(false)
  })

  it('검증 전·확정 후·적용할 행이 없을 때는 열지 않는다', () => {
    expect(canCommit(null)).toBe(false)
    expect(canCommit(result({ dryRun: false }))).toBe(false)
    expect(canCommit(result({ importedCount: 0 }))).toBe(false)
  })
})

describe('revisionSummary', () => {
  it('같은 수라도 검증과 확정을 다른 문장으로 쓴다', () => {
    expect(revisionSummary(result({ dryRun: true }))).not.toBe(
      revisionSummary(result({ dryRun: false })),
    )
  })

  it('오류가 있으면 그 수를 말한다', () => {
    const text = revisionSummary(
      result({
        errors: [
          { row: 2, field: 'year', message: 'a' },
          { row: 3, field: 'year', message: 'b' },
        ],
      }),
    )
    expect(text).toContain('2')
  })

  it('대체 행 수를 드러낸다 — 무엇이 바뀌는지가 확인 단계의 핵심이다', () => {
    expect(revisionSummary(result({ importedCount: 5, replacedCount: 4 }))).toContain('4')
  })
})

describe('actorLabel', () => {
  const base: ParameterRevisionEvent = {
    id: 'e1',
    timestamp: '2026-09-21T03:15:00+00:00',
    kind: 'regulation_years',
    actor: { displayName: '홍길동', email: 'office@example.com' },
    userId: '6a8b3660-0000-0000-0000-000000000001',
    importedCount: 1,
    replacedCount: 1,
    version: 'import.20260921T031500Z',
    sourceRefs: [],
  }

  it('행위자를 풀었으면 식별자 대신 사람을 보인다', () => {
    const label = actorLabel(base)
    expect(label).toContain('홍길동')
    expect(label).not.toContain(base.userId as string)
  })

  it('이름이 없으면 이메일로, 풀지 못했으면 식별자로 — 빈칸으로 두지 않는다', () => {
    expect(actorLabel({ ...base, actor: { displayName: null, email: 'a@b.c' } })).toContain('a@b.c')
    expect(actorLabel({ ...base, actor: null })).toContain(base.userId as string)
    expect(actorLabel({ ...base, actor: null, userId: null })).not.toBe('')
  })
})

describe('PARAMETER_KINDS', () => {
  it('서버 `§7.5` type 네 가지와 정확히 같다', () => {
    expect(PARAMETER_KINDS.map((spec) => spec.kind).sort()).toEqual(
      ['fuel_types', 'rating_boundaries', 'reference_lines', 'regulation_years'].sort(),
    )
  })
})
