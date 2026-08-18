import { describe, expect, it } from 'vitest'
import { createDemoProvider } from './demoProvider'
import { VoyageCiiError } from './provider'
import type { VoyageCiiRequest } from './types'

/**
 * 기대값의 출처가 두 가지다 — 검증 강도가 다르므로 구분한다.
 *
 * | 구분 | 케이스 | 성격 |
 * |---|---|---|
 * | **계약 유래** | Fixture 1 (HFO 80t) | `#132` 계약 코멘트의 기대 응답 전문. **외부에서 확정된 잠금** |
 * | **자체 도출** | 60 · 71 · 75 · 90 · 100t 등 | `PRD §3.3.6`·`§9.4.1`을 이 파일에서 손으로 적용해 만든 값. 프론트 로직이 틀리면 오류를 그대로 보존한다 |
 *
 * 자체 도출 케이스는 `#39`(등급 판정)·`#40`(위험도)이 머지되면 **백엔드 산출값과 대조**해야
 * 진짜 잠금이 된다(#134가 중복 구현을 감수하는 조건 ⑶).
 */

/**
 * `#132` 계약이 고정한 샘플 선박 UUID.
 * 배열 인덱스로 얻지 않는다 — 고정표 순서가 바뀌어도 Fixture 1의 입력은 그대로여야 한다.
 */
const FIXTURE_1_VESSEL_ID = '00000000-0000-4000-8000-000000000001'

/**
 * 고정표에 없는 선박 ID. **실재하는 선박의 ID가 아니다.**
 * `#34`의 샘플 선박 2·3번은 UUID가 아직 정해지지 않았으므로, 그 자리를 임의 값으로
 * 채우지 않고 미지원 경로 확인 전용 ID를 따로 둔다.
 */
const UNSUPPORTED_VESSEL_ID = '00000000-0000-4000-8000-0000ffffffff'

const provider = createDemoProvider()

/** `#132` 계약 §7의 8/8 provisional fixture 요청. */
const FIXTURE_1: VoyageCiiRequest = {
  vessel_id: FIXTURE_1_VESSEL_ID,
  regulation_year: 2026,
  distance_nm: 1000,
  speed_kn: 12.0,
  fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 80 }],
}

const withFuel = (fuelTon: number): VoyageCiiRequest => ({
  ...FIXTURE_1,
  fuel_uses: [{ fuel_type: 'HFO', fuel_ton: fuelTon }],
})

/** provider 인터페이스를 거쳐 오류를 받는다. 동기 throw가 아니라 rejection이어야 한다. */
async function expectError(request: VoyageCiiRequest): Promise<VoyageCiiError> {
  const error = await provider.estimate(request).then(
    () => null,
    (e: unknown) => e,
  )
  expect(error).toBeInstanceOf(VoyageCiiError)
  return error as VoyageCiiError
}

// ─────────────────────────────────────────────────────────────
// fixture 1/3 — 성공
// ─────────────────────────────────────────────────────────────
describe('성공 fixture — 계약 유래', () => {
  it('#132 계약의 기대 응답을 그대로 반환한다', async () => {
    const r = (await provider.estimate(FIXTURE_1)).data

    expect(r.attained_cii).toBe('4.982400')
    expect(r.required_cii).toBe('5.045066')
    expect(r.ratio_to_required).toBe('0.98758')
    expect(r.estimated_rating).toBe('C')
    expect(r.next_worse_boundary_margin).toBe('0.365370')
    expect(r.next_worse_boundary_margin_ratio).toBe('0.0724')
    expect(r.co2_emission_ton).toBe('249.12')
    expect(r.fuel_consumption_ton).toBe('80.00')
    expect(r.risk_level).toBe('MEDIUM')
  })

  it('capacity와 계산 근거를 계약대로 싣는다', async () => {
    const r = (await provider.estimate(FIXTURE_1)).data

    expect(r.transport_capacity).toBe('50000')
    expect(r.transport_capacity_basis).toBe('DWT')
    expect(r.reference_capacity).toBe('50000')
    expect(r.reference_capacity_rule).toBe('DWT')
    expect(r.calculation_basis).toEqual({
      ship_type: 'BULK_CARRIER',
      z_factor_percent: '11.0',
      fuel_cf_details: [{ fuel_type: 'HFO', cf: '3.114', fuel_ton: '80.0' }],
      a_decimal: '4745',
      c: '0.622',
    })
  })

  it('면책 문구와 경고를 항상 싣는다', async () => {
    const res = await provider.estimate(FIXTURE_1)
    // 정본 문구 (PRD §6.3 면책) — 바꾸려면 PRD 개정이 먼저다 (AGENTS §4.6).
    expect(res.disclaimer).toBe('참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.')
    expect(res.warnings).toContain('REFERENCE_ONLY')
  })

  it('Layer 1 값은 문자열이고 distance_nm만 숫자로 에코한다', async () => {
    const r = (await provider.estimate(FIXTURE_1)).data
    expect(r.distance_nm).toBe(1000)
    expect(typeof r.distance_nm).toBe('number')
    for (const key of [
      'attained_cii',
      'required_cii',
      'ratio_to_required',
      'co2_emission_ton',
      'fuel_consumption_ton',
      'transport_capacity',
      'reference_capacity',
    ] as const) {
      expect(typeof r[key]).toBe('string')
    }
  })

  it('동일 입력에 동일 결과를 반환한다', async () => {
    expect(await provider.estimate(FIXTURE_1)).toEqual(await provider.estimate(FIXTURE_1))
  })
})

// ─────────────────────────────────────────────────────────────
// 입력이 결과를 바꾸는가 — 자체 도출
// ─────────────────────────────────────────────────────────────
describe('입력이 결과를 바꾼다 — 자체 도출', () => {
  it('연료량을 늘리면 CO₂와 CII가 같은 방향으로 커진다', async () => {
    const base = (await provider.estimate(FIXTURE_1)).data
    const more = (await provider.estimate(withFuel(100))).data

    expect(Number(more.co2_emission_ton)).toBeGreaterThan(Number(base.co2_emission_ton))
    expect(Number(more.attained_cii)).toBeGreaterThan(Number(base.attained_cii))
  })

  it('거리만 늘리면 CO₂는 그대로이고 CII만 작아진다', async () => {
    const base = (await provider.estimate(FIXTURE_1)).data
    const far = (await provider.estimate({ ...FIXTURE_1, distance_nm: 2000 })).data

    expect(far.co2_emission_ton).toBe(base.co2_emission_ton)
    expect(Number(far.attained_cii)).toBeLessThan(Number(base.attained_cii))
  })

  it('연료 종류를 바꾸면 CF에 따라 CO₂와 CII가 변한다', async () => {
    // LNG는 CF 2.750으로 HFO 3.114보다 낮다 (DB_SCHEMA §3.2)
    const lng = (
      await provider.estimate({
        ...FIXTURE_1,
        fuel_uses: [{ fuel_type: 'LNG', fuel_ton: 80 }],
      })
    ).data

    expect(lng.co2_emission_ton).toBe('220.00')
    expect(Number(lng.attained_cii)).toBeLessThan(4.9824)
    expect(lng.calculation_basis.fuel_cf_details[0].cf).toBe('2.750')
  })

  it('속력만 바꾸면 결과가 변하지 않는다', async () => {
    // Layer 1 계산에 speed_kn이 들어가지 않는다 (PRD §10.3)
    const slow = (await provider.estimate({ ...FIXTURE_1, speed_kn: 8 })).data
    const fast = (await provider.estimate({ ...FIXTURE_1, speed_kn: 20 })).data
    expect(slow).toEqual(fast)
  })

  it('동일 연료 종류가 여러 행이면 합산한다', async () => {
    const split = (
      await provider.estimate({
        ...FIXTURE_1,
        fuel_uses: [
          { fuel_type: 'HFO', fuel_ton: 30 },
          { fuel_type: 'HFO', fuel_ton: 50 },
        ],
      })
    ).data

    expect(split.attained_cii).toBe('4.982400')
    expect(split.calculation_basis.fuel_cf_details).toHaveLength(1)
    expect(split.calculation_basis.fuel_cf_details[0].fuel_ton).toBe('80.0')
  })
})

// ─────────────────────────────────────────────────────────────
// 등급·위험도 경계 — 자체 도출
// ─────────────────────────────────────────────────────────────
// 규칙 자체(`<=` · `>=`)의 경계 조건은 rules.test.ts가 경계값을 직접 넣어 잠근다.
// 이 describe는 provider를 거친 경로가 그 규칙을 타는지 확인한다.
describe('경계를 넘도록 설계한 입력 — 자체 도출', () => {
  // 경계값(required 5.045066 기준): A ≤ 4.338757 < B ≤ 4.742362 < C ≤ 5.347770 < D ≤ 5.953178 < E
  // attained = fuel_ton × 3.114 / 50 (거리 1000nm · capacity 50,000 DWT)
  //
  // 위험도는 등급만이 아니라 여유율에도 걸린다 — PRD §9.4.1 원문:
  //   A 또는 B, margin_ratio ≥ 5% → LOW   |  A 또는 B, < 5% → MEDIUM
  //   C, margin_ratio ≥ 3% → MEDIUM       |  C, < 3% 또는 D → HIGH   |  E → CRITICAL
  it.each([
    { fuelTon: 60, attained: '3.736800', rating: 'A', risk: 'LOW' },
    { fuelTon: 71, attained: '4.421880', rating: 'B', risk: 'LOW' }, // 여유율 6.35% ≥ 5%
    { fuelTon: 75, attained: '4.671000', rating: 'B', risk: 'MEDIUM' }, // 여유율 1.41% < 5%
    { fuelTon: 80, attained: '4.982400', rating: 'C', risk: 'MEDIUM' }, // 여유율 7.24% ≥ 3%
    { fuelTon: 90, attained: '5.605200', rating: 'D', risk: 'HIGH' },
    { fuelTon: 100, attained: '6.228000', rating: 'E', risk: 'CRITICAL' },
  ])('연료 $fuelTon t → 등급 $rating · 위험도 $risk', async (c) => {
    const r = (await provider.estimate(withFuel(c.fuelTon))).data
    expect(r.attained_cii).toBe(c.attained)
    expect(r.estimated_rating).toBe(c.rating)
    expect(r.risk_level).toBe(c.risk)
  })

  it('등급 E는 다음 악화 경계가 없어 margin이 null이다', async () => {
    const r = (await provider.estimate(withFuel(100))).data
    expect(r.next_worse_boundary_margin).toBeNull()
    expect(r.next_worse_boundary_margin_ratio).toBeNull()
  })

  it('경계 바로 아래에서는 더 우수한 등급을 유지한다', async () => {
    // upper_boundary(5.3477703124)보다 아주 조금 낮은 attained를 만든다.
    // ⚠️ 이 케이스는 `<` 구간을 확인하는 것이지 `attained === boundary`를 확인하지
    // 않는다 — 부동소수점 나눗셈을 거치면 경계와 정확히 같은 값을 만들 수 없다.
    // 등호 분기(`<=`)는 rules.test.ts가 경계값을 직접 넣어 잠근다.
    const distance = 249_120_000 / (50_000 * 5.34777)
    const r = (await provider.estimate({ ...FIXTURE_1, distance_nm: distance })).data
    expect(r.attained_cii).toBe('5.347770')
    expect(r.estimated_rating).toBe('C') // D가 아니라 C
  })

  it('등급 C라도 여유율이 3% 미만이면 위험도가 HIGH가 된다', async () => {
    const r = (await provider.estimate(withFuel(85))).data // attained 5.2938
    expect(r.estimated_rating).toBe('C')
    expect(Number(r.next_worse_boundary_margin_ratio)).toBeLessThan(0.03)
    expect(r.risk_level).toBe('HIGH')
  })
})

// ─────────────────────────────────────────────────────────────
// fixture 2/3 — 입력 오류 (요청 값이 검증 규칙 위반)
// ─────────────────────────────────────────────────────────────
describe('입력 오류 fixture — VALIDATION_ERROR · UNKNOWN_FUEL_TYPE', () => {
  it.each([
    {
      label: '연료 사용량 0 (VAL-002)',
      req: () => withFuel(0),
      code: 'VALIDATION_ERROR',
      field: 'fuel_uses[0].fuel_ton',
    },
    {
      label: '연료 사용량 음수',
      req: () => withFuel(-1),
      code: 'VALIDATION_ERROR',
      field: 'fuel_uses[0].fuel_ton',
    },
    {
      label: '연료 목록 비어 있음',
      req: () => ({ ...FIXTURE_1, fuel_uses: [] }),
      code: 'VALIDATION_ERROR',
      field: 'fuel_uses',
    },
    {
      label: '거리 0 (VAL-002)',
      req: () => ({ ...FIXTURE_1, distance_nm: 0 }),
      code: 'VALIDATION_ERROR',
      field: 'distance_nm',
    },
    {
      label: '속도 1.0 미만 (VAL-009)',
      req: () => ({ ...FIXTURE_1, speed_kn: 0.5 }),
      code: 'VALIDATION_ERROR',
      field: 'speed_kn',
    },
    {
      label: '알 수 없는 연료 종류 (VAL-006)',
      req: () => ({
        ...FIXTURE_1,
        fuel_uses: [{ fuel_type: 'NUCLEAR', fuel_ton: 80 }],
      }),
      code: 'UNKNOWN_FUEL_TYPE',
      field: 'fuel_uses[0].fuel_type',
    },
  ])('$label → $code', async (c) => {
    const error = await expectError(c.req())
    expect(error.code).toBe(c.code)
    expect(error.field).toBe(c.field)
  })
})

// ─────────────────────────────────────────────────────────────
// fixture 3/3 — 계산 실패
//   입력 검증을 통과하고 고정표 조회도 성공했으나, 계산 결과가 유효하지 않은 경우.
//
//   ⚠️ #37 엔진의 출력 가드 [ORACLE-MISS-2]와 **가드 조건은 같으나 도달 경로가 다르다.**
//   백엔드는 Decimal(prec=30)이라 같은 입력에서 오버플로하지 않는다. 이 fixture는
//   백엔드 동작의 재현이 아니라 **demo provider의 float64 비정상 수치 방어**를 검증한다.
//   demo provider는 #138 이후에도 개발·테스트용으로 남으므로 이 테스트도 유효하게 남는다.
// ─────────────────────────────────────────────────────────────
describe('계산 실패 fixture — CALCULATION_ERROR', () => {
  it('연료량이 극단적으로 크면 총 CO₂가 Infinity가 되어 계산이 실패한다', async () => {
    // fuel_ton > 0 이라 입력 검증은 통과한다. 선박·연도도 지원 조합이다.
    // 1e308 × 3.114 × 1e6 → Infinity
    const error = await expectError(withFuel(1e308))
    expect(error.code).toBe('CALCULATION_ERROR')
    expect(error.field).toBe('fuel_uses')
  })

  it('거리가 극단적으로 크면 attained_cii가 0으로 붕괴해 계산이 실패한다', async () => {
    const error = await expectError({ ...FIXTURE_1, distance_nm: 1e308 })
    expect(error.code).toBe('CALCULATION_ERROR')
    expect(error.field).toBe('distance_nm')
  })

  it('계산 실패는 미지원 조합 오류와 다른 코드를 쓴다', async () => {
    const calc = await expectError(withFuel(1e308))
    const unsupported = await expectError({ ...FIXTURE_1, regulation_year: 2030 })
    expect(calc.code).not.toBe(unsupported.code)
  })
})

// ─────────────────────────────────────────────────────────────
// 미지원 조합 — 고정표 조회 실패 (계산 실패와 구분한다)
// ─────────────────────────────────────────────────────────────
describe('미지원 조합 — 고정표 조회 실패', () => {
  it('고정표에 없는 선박은 임의 계산하지 않고 실패한다', async () => {
    const error = await expectError({
      ...FIXTURE_1,
      vessel_id: UNSUPPORTED_VESSEL_ID,
    })
    expect(error.code).toBe('UNSUPPORTED_VESSEL')
    expect(error.field).toBe('vessel_id')
  })

  it('고정표에 없는 연도는 임의 계산하지 않고 실패한다', async () => {
    const error = await expectError({ ...FIXTURE_1, regulation_year: 2030 })
    expect(error.code).toBe('UNSUPPORTED_YEAR')
    expect(error.field).toBe('regulation_year')
    expect(error.message).toContain('2026') // 지원 연도를 안내한다
  })

  it('오류는 동기 throw가 아니라 rejection으로 전달된다', async () => {
    // 화면이 .catch()로 받을 수 있어야 하고, 실제 API provider와 동작이 같아야 한다
    const settled = provider.estimate({ ...FIXTURE_1, regulation_year: 2030 })
    expect(settled).toBeInstanceOf(Promise)
    await expect(settled).rejects.toBeInstanceOf(VoyageCiiError)
  })
})
