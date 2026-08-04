import { describe, expect, it } from 'vitest'
import {
  RISK_THRESHOLD,
  determineRating,
  determineRiskLevel,
  nextWorseBoundary,
  type Boundaries,
} from './rules'

/**
 * 경계 조건 전용 테스트.
 *
 * provider를 통한 요청으로는 `attained_cii`가 경계와 **정확히 같은** 입력을 만들기
 * 어렵다 — 부동소수점 나눗셈을 거치기 때문이다. 그래서 규칙 함수에 경계값을 직접
 * 넣어 `<=`/`>=` 를 잠근다. `<`/`>` 로 잘못 구현하면 여기서 실패한다.
 */

/** Fixture 1(BULK_CARRIER 50,000 DWT × 2026)의 경계값. `PRD §13.1` 전체 자릿수. */
const B: Boundaries = {
  superior: 4.3387570460,
  lower: 4.7423623525,
  upper: 5.3477703124,
  inferior: 5.9531782723,
}

describe('determineRating — PRD §3.3.6', () => {
  it('구간 안쪽 값을 올바른 등급으로 판정한다', () => {
    expect(determineRating(3.0, B)).toBe('A')
    expect(determineRating(4.5, B)).toBe('B')
    expect(determineRating(5.0, B)).toBe('C')
    expect(determineRating(5.6, B)).toBe('D')
    expect(determineRating(7.0, B)).toBe('E')
  })

  // 핵심 — "경계값과 정확히 같은 경우에는 더 우수한 등급으로 판정한다"
  it.each([
    { at: B.superior, expected: 'A', worse: 'B' },
    { at: B.lower, expected: 'B', worse: 'C' },
    { at: B.upper, expected: 'C', worse: 'D' },
    { at: B.inferior, expected: 'D', worse: 'E' },
  ])(
    '경계값 $at 과 정확히 같으면 $worse 가 아니라 $expected 로 판정한다',
    ({ at, expected }) => {
      expect(determineRating(at, B)).toBe(expected)
    },
  )

  it('경계값을 아주 조금이라도 넘으면 등급이 내려간다', () => {
    expect(determineRating(nextUp(B.superior), B)).toBe('B')
    expect(determineRating(nextUp(B.lower), B)).toBe('C')
    expect(determineRating(nextUp(B.upper), B)).toBe('D')
    expect(determineRating(nextUp(B.inferior), B)).toBe('E')
  })
})

describe('nextWorseBoundary', () => {
  it('등급별로 다음 악화 경계를 돌려준다', () => {
    expect(nextWorseBoundary('A', B)).toBe(B.superior)
    expect(nextWorseBoundary('B', B)).toBe(B.lower)
    expect(nextWorseBoundary('C', B)).toBe(B.upper)
    expect(nextWorseBoundary('D', B)).toBe(B.inferior)
  })

  it('등급 E는 더 나쁜 등급이 없어 null이다', () => {
    expect(nextWorseBoundary('E', B)).toBeNull()
  })
})

describe('determineRiskLevel — PRD §9.4.1', () => {
  it('등급 D·E는 여유율과 무관하다', () => {
    expect(determineRiskLevel('E', null)).toBe('CRITICAL')
    expect(determineRiskLevel('E', 0.99)).toBe('CRITICAL')
    expect(determineRiskLevel('D', 0.99)).toBe('HIGH')
    expect(determineRiskLevel('D', null)).toBe('HIGH')
  })

  // 핵심 — 임계값에서 정확히 같으면 완화된 쪽(≥)
  it.each(['A', 'B'] as const)('등급 %s: 여유율이 정확히 5%%면 LOW', (rating) => {
    expect(determineRiskLevel(rating, RISK_THRESHOLD.superiorGrades)).toBe('LOW')
    expect(determineRiskLevel(rating, nextDown(RISK_THRESHOLD.superiorGrades))).toBe(
      'MEDIUM',
    )
    expect(determineRiskLevel(rating, nextUp(RISK_THRESHOLD.superiorGrades))).toBe('LOW')
  })

  it('등급 C: 여유율이 정확히 3%면 MEDIUM', () => {
    expect(determineRiskLevel('C', RISK_THRESHOLD.gradeC)).toBe('MEDIUM')
    expect(determineRiskLevel('C', nextDown(RISK_THRESHOLD.gradeC))).toBe('HIGH')
    expect(determineRiskLevel('C', nextUp(RISK_THRESHOLD.gradeC))).toBe('MEDIUM')
  })

  it('등급 A·B와 C의 임계값이 서로 다르다', () => {
    // 4%는 A·B에서는 MEDIUM, C에서는 MEDIUM — 같은 결과지만 경로가 다르다
    expect(determineRiskLevel('B', 0.04)).toBe('MEDIUM') // < 5%
    expect(determineRiskLevel('C', 0.04)).toBe('MEDIUM') // ≥ 3%
    // 2%는 갈린다
    expect(determineRiskLevel('B', 0.02)).toBe('MEDIUM')
    expect(determineRiskLevel('C', 0.02)).toBe('HIGH')
  })

  it('등급 A~C에서 여유율이 없으면 보수적으로 HIGH', () => {
    expect(determineRiskLevel('C', null)).toBe('HIGH')
  })

  it('임계값 상수가 PRD §9.4.1 값과 같다', () => {
    expect(RISK_THRESHOLD).toEqual({ superiorGrades: 0.05, gradeC: 0.03 })
  })
})

/** 다음으로 표현 가능한 double. 경계 바로 바깥을 만들기 위한 것. */
function nextUp(v: number): number {
  const buf = new DataView(new ArrayBuffer(8))
  buf.setFloat64(0, v)
  buf.setBigUint64(0, buf.getBigUint64(0) + 1n)
  return buf.getFloat64(0)
}

/** 바로 아래 double. */
function nextDown(v: number): number {
  const buf = new DataView(new ArrayBuffer(8))
  buf.setFloat64(0, v)
  buf.setBigUint64(0, buf.getBigUint64(0) - 1n)
  return buf.getFloat64(0)
}
