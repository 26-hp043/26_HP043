import { describe, expect, it } from 'vitest'
import { createDemoAnnualProvider } from './demoProvider'
import { FIXED_PARAMETERS, FUEL_CF } from '../voyage-cii/referenceTable'

const provider = createDemoAnnualProvider()

describe('예시 데이터임이 응답에 드러난다', () => {
  it('is_sample_data가 true다', async () => {
    // 화면이 배지를 상수로 박으면 #63·#64 연결 후에도 남는다. 응답에서 판단한다.
    expect((await provider.load()).is_sample_data).toBe(true)
  })

  it('REFERENCE_ONLY 경고와 면책 문구를 함께 낸다', async () => {
    const result = await provider.load()
    expect(result.warnings).toContain('REFERENCE_ONLY')
    expect(result.disclaimer).toBe('참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.')
  })
})

describe('확률을 내지 않는다', () => {
  it('응답에 확률 필드가 없다', async () => {
    // DESIGN_SYSTEM §2.5 (a) 임계값이 초안이고 P(D∪E) 계산 정의가 PRD에 없다(#170 ⑶).
    const keys = Object.keys(await provider.load())
    expect(keys.filter((k) => /probab|prob_|p_de/i.test(k))).toEqual([])
  })
})

describe('목업이 스스로 모순되지 않는다', () => {
  it('합계가 월별 행의 합과 같다', async () => {
    const r = await provider.load()
    const distance = r.months.reduce((s, m) => s + m.distance_nm, 0)
    const fuel = r.months.reduce((s, m) => s + Number(m.fuel_ton), 0)
    expect(r.total_distance_nm).toBe(distance)
    expect(Number(r.total_fuel_ton)).toBeCloseTo(fuel, 2)
  })

  it('CO₂가 연료 × CF와 같다', async () => {
    const r = await provider.load()
    const cf = Number(FUEL_CF.HFO.cf)
    expect(Number(r.total_co2_emission_ton)).toBeCloseTo(Number(r.total_fuel_ton) * cf, 2)
  })

  it('연간 CII가 누적 CO₂ ÷ (capacity × 누적 거리)다', async () => {
    const r = await provider.load()
    const expected =
      (Number(r.total_co2_emission_ton) * 1_000_000) / (50000 * r.total_distance_nm)
    expect(Number(r.attained_cii)).toBeCloseTo(expected, 6)
  })

  it('월별 CII도 그 달의 값과 맞는다', async () => {
    // 표시용 co2_emission_ton은 소수 2자리로 반올림돼 있으므로 그 값으로 되짚으면
    // 어긋난다. CII는 반올림 전 값으로 산출된다 — DESIGN_SYSTEM §4.2 「반올림」 🔒.
    const r = await provider.load()
    const cf = Number(FUEL_CF.HFO.cf)
    for (const m of r.months) {
      const expected = (Number(m.fuel_ton) * cf * 1_000_000) / (50000 * m.distance_nm)
      expect(Number(m.attained_cii)).toBeCloseTo(expected, 6)
    }
  })

  it('required_cii가 고정표와 같다', async () => {
    const r = await provider.load()
    expect(Number(r.required_cii)).toBeCloseTo(Number(FIXED_PARAMETERS[0].requiredCii), 6)
  })

  it('연간 CII가 월별 최소·최대 사이에 있다', async () => {
    const r = await provider.load()
    const monthly = r.months.map((m) => Number(m.attained_cii))
    expect(Number(r.attained_cii)).toBeGreaterThanOrEqual(Math.min(...monthly))
    expect(Number(r.attained_cii)).toBeLessThanOrEqual(Math.max(...monthly))
  })
})

describe('등급·위험도는 기능①과 같은 규칙으로 낸다', () => {
  it('시연 데이터가 등급 C · 보통 MEDIUM으로 나온다', async () => {
    const r = await provider.load()
    expect(r.estimated_rating).toBe('C')
    expect(r.risk_level).toBe('MEDIUM')
  })

  it('여유율이 있다 — 등급 E가 아니므로 null이 아니다', async () => {
    const r = await provider.load()
    expect(r.next_worse_boundary_margin_ratio).not.toBeNull()
  })

  it('ratio_to_required = attained ÷ required', async () => {
    const r = await provider.load()
    expect(Number(r.ratio_to_required)).toBeCloseTo(
      Number(r.attained_cii) / Number(r.required_cii),
      5,
    )
  })
})

describe('결정성', () => {
  it('같은 결과가 반복된다 — 고정값 목업이다', async () => {
    expect(await provider.load()).toEqual(await provider.load())
  })
})

describe('Layer 1 값이 문자열이다', () => {
  it('수치 필드가 문자열로 온다', async () => {
    const r = await provider.load()
    for (const key of [
      'required_cii',
      'attained_cii',
      'ratio_to_required',
      'total_fuel_ton',
      'total_co2_emission_ton',
    ] as const) {
      expect(typeof r[key]).toBe('string')
    }
    for (const m of r.months) {
      expect(typeof m.fuel_ton).toBe('string')
      expect(typeof m.attained_cii).toBe('string')
    }
  })

  it('입력 에코 성격의 필드는 숫자다', async () => {
    const r = await provider.load()
    expect(typeof r.total_distance_nm).toBe('number')
    expect(typeof r.months[0].voyage_count).toBe('number')
  })
})
