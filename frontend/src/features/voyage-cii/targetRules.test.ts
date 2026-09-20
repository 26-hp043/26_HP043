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

describe('경계 CII는 서버 값 그대로다 (#1371)', () => {
  /*
   * 종전에는 `required_cii`(표시용 6자리 문자열)를 float로 바꿔 d-vector를 곱했다.
   * 411,120건 스캔에서 87건(0.021%)의 끝자리가 서버 값과 달랐다 — 예: BULK
   * 274,178 DWT 2026 lower, 서버 `1.645` vs 화면 `1.646`. 등급 판정은 서버가 하므로
   * 등급이 틀리지는 않지만, 화면이 「이 값 이하면 B」라고 적는 숫자가 서버와 다르다.
   */
  const SERVER_BOUNDARIES = {
    superior_boundary: '1.000001',
    lower_boundary: '2.000002',
    upper_boundary: '3.000003',
    inferior_boundary: '4.000004',
  }

  it('서버가 실어 준 값을 그대로 쓴다 — 다시 곱하지 않는다', () => {
    const targets = gradeTargets(
      { ...DATA, estimated_rating: 'E', rating_boundary_cii: SERVER_BOUNDARIES },
      BOUNDARY,
    )

    // 서버 값(6자리)을 **표시 자릿수(3자리)로 한 번만** 줄인다 — 곱셈이 없다.
    expect(targets.map((t) => t.boundaryCii)).toEqual(['1.000', '2.000', '3.000', '4.000'])
  })

  it('끝자리가 갈리는 실제 조합에서 서버 값을 따른다', () => {
    // `required × d`를 float로 계산하면 `1.646`, 서버 정본은 `1.645`인 조합이다.
    const targets = gradeTargets(
      {
        ...DATA,
        estimated_rating: 'B',
        required_cii: '1.851449',
        attained_cii: '1.700000',
        rating_boundary_cii: { ...SERVER_BOUNDARIES, superior_boundary: '1.645' },
      },
      { ...BOUNDARY, d1: '0.888771' },
    )

    expect(targets).toHaveLength(1)
    expect(targets[0].boundaryCii).toBe('1.645')
    // 곱셈으로 되살리면 여기서 갈린다 — 이중 반올림이 3번째 자리를 올린다.
    expect((1.851449 * 0.888771).toFixed(3)).toBe('1.646')
  })

  it('서버가 싣지 않은 응답(옛 이력)에서는 곱셈으로 되살린다', () => {
    const targets = gradeTargets({ ...DATA, rating_boundary_cii: null }, BOUNDARY)

    expect(targets.length).toBeGreaterThan(0)
    expect(targets[0].boundaryCii).toMatch(/^\d+\.\d{3}$/)
  })
})
