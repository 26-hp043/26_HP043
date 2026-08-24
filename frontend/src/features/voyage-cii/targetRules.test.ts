import { describe, expect, it } from 'vitest'
import { gradeTargets } from './targetRules'

/*
 * 화면에서 실제로 나온 값이다 — 샘플 벌크선 50,000 DWT · 5,000 nm ·
 * LPG(프로판) 800 t. `ratio_to_required`가 190.3%로 화면과 일치한다.
 */
const DATA = {
  estimated_rating: 'E' as const,
  required_cii: '5.045',
  attained_cii: '9.600',
  fuel_consumption_ton: '800',
}

/** IMO dd-vector — 응답 `parameters_used.rating_boundary` 그대로다. */
const BOUNDARY = { d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18' }

/** 이 항차의 상수 — 검산용. 50,000 DWT × 5,000 nm, LPG 프로판 CF 3.0. */
const CAPACITY = 50000
const DISTANCE = 5000
const CF = 3.0

describe('목표 등급 역산 (#727)', () => {
  it('현재보다 나은 등급만, 좋은 순서로 낸다', () => {
    const targets = gradeTargets(DATA, BOUNDARY)
    expect(targets.map((t) => t.rating)).toEqual(['A', 'B', 'C', 'D'])
  })

  it('경계 CII는 required_cii × d 다', () => {
    const targets = gradeTargets(DATA, BOUNDARY)
    // 5.045 × 1.06 = 5.3477
    expect(targets[2].boundaryCii).toBe('5.348')
    expect(targets[3].boundaryCii).toBe('5.953')
  })

  /*
   * 이 테스트가 이 모듈의 존재 이유를 잠근다. 「연료를 이만큼까지 쓰면 그 등급」
   * 이라고 적는 자리이므로, 그 연료를 실제로 태웠을 때 CII가 경계를 **넘으면
   * 안 된다.** 반올림이면 0.05 t 위로 올라가 넘는 경우가 생기고, 화면은 그것을
   * 「이 값이면 C 등급」이라고 단언하게 된다.
   */
  it('허용 연료를 되돌려 계산한 CII가 경계를 넘지 않는다 — 내림이라야 참이다', () => {
    for (const target of gradeTargets(DATA, BOUNDARY)) {
      const backCii = (Number(target.allowedFuelTon) * CF * 1e6) / (CAPACITY * DISTANCE)
      expect(backCii).toBeLessThanOrEqual(Number(target.boundaryCii))
    }
  })

  it('허용 + 감축 = 현재 연료 — 화면에서 두 값을 빼 보게 된다', () => {
    for (const target of gradeTargets(DATA, BOUNDARY)) {
      const sum = Number(target.allowedFuelTon) + Number(target.reduceFuelTon)
      expect(sum).toBeCloseTo(Number(DATA.fuel_consumption_ton), 6)
    }
  })

  it('감축률은 감축량 ÷ 현재 연료 다', () => {
    const targets = gradeTargets(DATA, BOUNDARY)
    // D 등급: 800 → 496.0, 감축 304.0 t = 38.0%
    expect(targets[3].allowedFuelTon).toBe('496.0')
    expect(targets[3].reduceFuelTon).toBe('304.0')
    expect(targets[3].reducePercent).toBe('38.0')
  })

  it('등급 A는 오를 곳이 없어 빈 배열이다', () => {
    expect(gradeTargets({ ...DATA, estimated_rating: 'A' }, BOUNDARY)).toEqual([])
  })

  it('등급 B는 A 한 줄만 낸다', () => {
    const targets = gradeTargets(
      { ...DATA, estimated_rating: 'B', attained_cii: '4.700' },
      BOUNDARY,
    )
    expect(targets.map((t) => t.rating)).toEqual(['A'])
  })

  it('읽히지 않는 값이 하나라도 있으면 통째로 빈 배열이다', () => {
    /*
     * 일부만 그리면 빠진 등급이 「방법이 없다」로 읽힌다 — 사실이 아니다.
     */
    expect(gradeTargets({ ...DATA, required_cii: '' }, BOUNDARY)).toEqual([])
    expect(gradeTargets({ ...DATA, attained_cii: '0' }, BOUNDARY)).toEqual([])
    expect(gradeTargets({ ...DATA, fuel_consumption_ton: '0' }, BOUNDARY)).toEqual([])
    expect(gradeTargets(DATA, { ...BOUNDARY, d3: '알 수 없음' })).toEqual([])
  })

  it('등급과 수치가 어긋난 응답에는 안내를 지어내지 않는다', () => {
    /*
     * 등급은 E인데 실적이 D 경계보다 낮다 — 그러면 D의 허용 연료가 현재
     * 연료보다 많아진다. 「더 태워도 된다」는 감축 안내가 될 수 없다.
     */
    expect(gradeTargets({ ...DATA, attained_cii: '5.000' }, BOUNDARY)).toEqual([])
  })
})
