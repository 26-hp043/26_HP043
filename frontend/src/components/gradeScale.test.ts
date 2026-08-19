import { describe, expect, it } from 'vitest'
import { buildGradeScale, type DVector } from './gradeScale'

/**
 * 등급 스케일 바의 기하 — `DESIGN_SYSTEM §9.4` 🔒.
 *
 * 이 컴포넌트의 결함은 **비례**에서 난다. 균등 분할로 그려도 화면은 멀쩡하고,
 * 「C에서 D까지가 B에서 C까지와 같다」는 틀린 감각만 남는다.
 */

/** `API_SPEC §4.1` 예시의 d-vector. 실제 경계는 균등하지 않다. */
const D: DVector = { d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18' }

const bandOf = (scale: NonNullable<ReturnType<typeof buildGradeScale>>, r: string) =>
  scale.bands.find((b) => b.rating === r)!

describe('buildGradeScale — 구간 비례', () => {
  it('안쪽 세 구간이 경계 간격에 정확히 비례한다', () => {
    const scale = buildGradeScale('1.00', D)!
    const b = bandOf(scale, 'B').fraction
    const c = bandOf(scale, 'C').fraction
    const d = bandOf(scale, 'D').fraction

    // d2-d1 = 0.08, d3-d2 = 0.12, d4-d3 = 0.12
    expect(c / b).toBeCloseTo(0.12 / 0.08, 10)
    expect(d / c).toBeCloseTo(1, 10)
  })

  it('균등 분할이 아니다', () => {
    // 다섯 구간이 모두 0.2면 §9.4 위반이다.
    const scale = buildGradeScale('1.00', D)!
    expect(scale.bands.every((band) => Math.abs(band.fraction - 0.2) < 1e-9)).toBe(false)
  })

  it('구간 폭의 합이 1이다', () => {
    const scale = buildGradeScale('1.00', D)!
    const total = scale.bands.reduce((sum, band) => sum + band.fraction, 0)
    expect(total).toBeCloseTo(1, 10)
  })

  it('경계 간격이 다른 선종에서도 비례가 유지된다', () => {
    // 간격 0.10 / 0.05 / 0.20
    const scale = buildGradeScale('1.00', {
      d1: '0.80',
      d2: '0.90',
      d3: '0.95',
      d4: '1.15',
    })!
    const b = bandOf(scale, 'B').fraction
    const c = bandOf(scale, 'C').fraction
    const d = bandOf(scale, 'D').fraction
    expect(b / c).toBeCloseTo(0.1 / 0.05, 10)
    expect(d / c).toBeCloseTo(0.2 / 0.05, 10)
  })

  it('다섯 구간을 A~E 순서로 낸다', () => {
    expect(buildGradeScale('1.00', D)!.bands.map((b) => b.rating)).toEqual([
      'A',
      'B',
      'C',
      'D',
      'E',
    ])
  })
})

describe('buildGradeScale — 마커 위치', () => {
  it('경계 위의 값은 그 경계에 선다', () => {
    const scale = buildGradeScale('0.94', D)!
    // A와 B의 폭을 합한 지점이 곧 d2다.
    const upToC = bandOf(scale, 'A').fraction + bandOf(scale, 'B').fraction
    expect(scale.markerFraction).toBeCloseTo(upToC, 10)
  })

  it('C 구간 한가운데 값이 C 구간 한가운데 선다', () => {
    const scale = buildGradeScale('1.00', D)! // (0.94 + 1.06) / 2
    const a = bandOf(scale, 'A').fraction
    const b = bandOf(scale, 'B').fraction
    const c = bandOf(scale, 'C').fraction
    expect(scale.markerFraction).toBeCloseTo(a + b + c / 2, 10)
  })

  it('A 한참 안쪽 값도 트랙 안에 있다', () => {
    // demo fixture의 실제 값. 잘라 내면 「경계 바로 아래」로 잘못 읽힌다.
    const scale = buildGradeScale('0.741', D)!
    expect(scale.markerFraction).toBeGreaterThan(0)
    expect(scale.markerFraction).toBeLessThan(bandOf(scale, 'A').fraction)
  })

  it('E 한참 바깥 값도 트랙 안에 있다', () => {
    const scale = buildGradeScale('2.5', D)!
    const upToE = 1 - bandOf(scale, 'E').fraction
    expect(scale.markerFraction).toBeGreaterThan(upToE)
    expect(scale.markerFraction).toBeLessThan(1)
  })

  it('극단값에서도 잘리지 않는다', () => {
    for (const v of ['0.01', '0.5', '1.0', '1.18', '10', '100']) {
      const scale = buildGradeScale(v, D)!
      expect(scale.markerFraction).toBeGreaterThanOrEqual(0)
      expect(scale.markerFraction).toBeLessThanOrEqual(1)
    }
  })

  it('값이 멀어져도 안쪽 세 구간의 비례는 그대로다', () => {
    // 끝 구간 폭은 값에 따라 변해도 B:C:D는 불변이어야 한다.
    const near = buildGradeScale('1.00', D)!
    const far = buildGradeScale('0.2', D)!
    const ratio = (s: typeof near) => bandOf(s, 'C').fraction / bandOf(s, 'B').fraction
    expect(ratio(near)).toBeCloseTo(ratio(far), 10)
  })
})

describe('buildGradeScale — 그리지 않는 경우', () => {
  it('값이 숫자가 아니면 null', () => {
    expect(buildGradeScale('N/A', D)).toBeNull()
  })

  it('빈 문자열을 0으로 읽지 않는다', () => {
    // `Number('')`은 NaN이 아니라 0이다. 그대로 두면 마커가 A 구간 맨 왼쪽에
    // 조용히 서서 「최고 등급」이라는 틀린 말을 한다.
    expect(buildGradeScale('', D)).toBeNull()
    expect(buildGradeScale('   ', D)).toBeNull()
    expect(buildGradeScale('1.0', { ...D, d2: '' })).toBeNull()
  })

  it('경계가 숫자가 아니면 null', () => {
    expect(buildGradeScale('1.0', { ...D, d3: 'oops' })).toBeNull()
  })

  it('경계가 오름차순이 아니면 null', () => {
    // 뒤집힌 경계를 그리면 구간 폭이 음수가 되어 레이아웃이 조용히 어긋난다.
    expect(buildGradeScale('1.0', { ...D, d3: '0.90' })).toBeNull()
  })

  it('경계가 같으면 null', () => {
    expect(buildGradeScale('1.0', { ...D, d2: '0.86' })).toBeNull()
  })
})
