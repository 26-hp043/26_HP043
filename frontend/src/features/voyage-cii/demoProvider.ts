import type {
  CalculationBasis,
  FuelCfDetail,
  VoyageCiiRequest,
  VoyageCiiResponse,
} from './types'
import {
  determineRating,
  determineRiskLevel,
  nextWorseBoundary,
  type Boundaries,
} from './rules'
import { VoyageCiiError, type VoyageCiiProvider } from './provider'
import {
  FUEL_CF,
  findFixedParameters,
  findVessel,
  supportedYears,
} from './referenceTable'

/**
 * 8/8 데모용 provider.
 *
 * ⚠️ **로컬 데모 전용 임시 구현이다.** 실제 API 연결(#138) 이후에는 개발·테스트용으로만
 * 남기고 운영 경로에서 쓰지 않는다.
 *
 * ## 무엇을 계산하고 무엇을 조회하는가
 *
 * | 값 | 출처 |
 * |---|---|
 * | `required_cii` · 등급 경계 4개 | **고정표 조회** — `#45`·`#38` 확정에 걸려 있어 계산하지 않는다 |
 * | CO₂ · `W` · `attained_cii` · 비율 · 등급 · margin · 위험도 | **매 요청 계산** |
 *
 * 등급·위험도까지 고정하면 연료량·거리를 바꿔도 결과가 그대로여서 시연 중에 드러난다.
 *
 * ## 등급·위험도는 백엔드보다 먼저 만들어지는 중복 구현이다
 *
 * `#39`(등급 판정)·`#40`(위험도)보다 앞서므로, `PRD §3.3.6` 판정 순서와 `§9.4.1`
 * 위험도 표를 **그대로 옮기고** Fixture 1로 잠근다. 두 이슈가 머지되면 대조한다.
 * 규칙 자체는 경계 조건을 직접 잠글 수 있도록 `rules.ts`로 분리했다.
 *
 * ## 내부 계산은 JavaScript 숫자로 한다
 *
 * `#134` 표시 규칙대로다 — `parseFloat`·`Number` 금지는 **UI 층에만** 적용되고
 * provider 내부는 허용된다. 계산 후 API 형식의 문자열로 직렬화하며, 이 경로의
 * 부동소수점 오차는 표시 자릿수(3~6자리)에서 드러나지 않는다. 실제 API 연결 시 사라진다.
 */

/**
 * 응답 문자열의 자릿수.
 *
 * `#132` 계약의 기대 응답 표기를 그대로 재현한다. **최종 자릿수 정책은 `#38` 소관**이며
 * 여기 값은 잠정이다 — 계약 예시가 `"11"`/`"11.0"`처럼 항목마다 다른 것도 기지 사항이라
 * 임의로 통일하지 않는다.
 */
const SERIALIZATION_DIGITS = {
  attainedCii: 6,
  /** 고정표는 전체 자릿수로 보관하고 응답에서만 자른다 — referenceTable.ts 참조 */
  requiredCii: 6,
  ratioToRequired: 5,
  margin: 6,
  marginRatio: 4,
  co2Ton: 2,
  fuelTon: 2,
  /** `calculation_basis.fuel_cf_details[].fuel_ton` — 계약 예시가 `"80.0"` */
  detailFuelTon: 1,
} as const

/** 데모 응답의 고정 메타. 실제 API에서는 서버가 생성한다. */
const DEMO_MODEL_VERSION = {
  engine: 'dual-precision-v1',
  decimal_precision: 30,
  decimal_rounding: 'ROUND_HALF_UP',
  rng_algorithm: 'PCG64DXSM',
  numpy_version: '2.1.0',
  python_version: '3.12.4',
} as const

/**
 * ⚠️ **계산되지 않은 demo stub이다.** 원칙적으로는 같은 입력·파라미터면 동일하게 나오는
 * 결정적 값이지만, 아래는 provisional provider의 비검증 예시이며 canonical hash가 아니다.
 * 화면은 이 값에 의존하면 안 된다(#132 계약 §7).
 */
const DEMO_INPUT_HASH =
  'sha256:0000000000000000000000000000000000000000000000000000000000000001'
const DEMO_PARAMETER_HASH =
  'sha256:0000000000000000000000000000000000000000000000000000000000000002'

/** `PRD §6.3` "모든 결과 화면" 문구. */
const DISCLAIMER = '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.'

export function createDemoProvider(): VoyageCiiProvider {
  return {
    // `async`로 둔다 — 내부에서 동기적으로 던진 오류도 rejection이 되어야
    // 실제 API provider(`fetch` 기반)와 호출 측 계약이 같아진다.
    async estimate(request) {
      return computeVoyageCii(request)
    },
  }
}

/**
 * 계산 본체. **export하지 않는다** — 화면과 테스트는 `VoyageCiiProvider` 인터페이스를
 * 거쳐야 실제 API provider로 교체했을 때 같은 경로가 검증된다.
 */
function computeVoyageCii(request: VoyageCiiRequest): VoyageCiiResponse {
  validateRequest(request)

  const vessel = findVessel(request.vessel_id)
  if (!vessel) {
    throw new VoyageCiiError(
      'UNSUPPORTED_VESSEL',
      '데모에서 지원하지 않는 선박입니다. 샘플 선박을 선택해 주세요.',
      'vessel_id',
    )
  }

  const fixed = findFixedParameters(request.vessel_id, request.regulation_year)
  if (!fixed) {
    const years = supportedYears(request.vessel_id).join(', ')
    throw new VoyageCiiError(
      'UNSUPPORTED_YEAR',
      `데모에서 지원하지 않는 기준연도입니다. 지원 연도: ${years}`,
      'regulation_year',
    )
  }

  // 동일 fuel_type을 합산한다 (계약 §3 · cii_engine.py와 같은 규칙)
  const merged = new Map<string, number>()
  for (const use of request.fuel_uses) {
    merged.set(use.fuel_type, (merged.get(use.fuel_type) ?? 0) + use.fuel_ton)
  }

  // M = Σ(FuelConsumed_j × 1,000,000 × CF_j)   — PRD §3.3.2
  let totalCo2G = 0
  let totalFuelTon = 0
  const details: FuelCfDetail[] = []
  for (const [fuelType, fuelTon] of merged) {
    const cf = FUEL_CF[fuelType].cf
    totalCo2G += fuelTon * Number(cf) * 1_000_000
    totalFuelTon += fuelTon
    details.push({
      fuel_type: fuelType,
      cf,
      fuel_ton: toFixedString(fuelTon, SERIALIZATION_DIGITS.detailFuelTon),
    })
  }

  // W = transport_capacity × Distance_nm       — PRD §3.3.3
  const transportCapacity = Number(vessel.transportCapacity)
  const transportWork = transportCapacity * request.distance_nm

  // attained_CII = M / W                       — PRD §3.3.1
  const attainedCii = totalCo2G / transportWork
  const requiredCii = Number(fixed.requiredCii)
  const ratioToRequired = attainedCii / requiredCii

  // 출력 가드 — #37 엔진의 [ORACLE-MISS-2]와 **가드 조건은 같으나 도달 경로가 다르다.**
  //   프론트: float64라 1e308 × 3.114e6에서 Infinity가 된다
  //   백엔드: Decimal(prec=30)은 같은 입력에서 오버플로하지 않고 큰 값을 반환한다
  // 즉 이 가드는 백엔드 동작의 재현이 아니라 **demo provider 전용 비정상 수치 방어**다.
  // demo provider는 #138 이후에도 개발·테스트용으로 남으므로 이 가드도 함께 남는다.
  if (!Number.isFinite(totalCo2G) || totalCo2G <= 0) {
    throw new VoyageCiiError(
      'CALCULATION_ERROR',
      '계산 결과가 유효하지 않습니다. 입력값을 확인해 주세요.',
      'fuel_uses',
    )
  }
  if (!Number.isFinite(attainedCii) || attainedCii <= 0) {
    throw new VoyageCiiError(
      'CALCULATION_ERROR',
      '계산 결과가 유효하지 않습니다. 입력값을 확인해 주세요.',
      'distance_nm',
    )
  }

  const boundaries: Boundaries = {
    superior: Number(fixed.boundaries.superior),
    lower: Number(fixed.boundaries.lower),
    upper: Number(fixed.boundaries.upper),
    inferior: Number(fixed.boundaries.inferior),
  }
  const rating = determineRating(attainedCii, boundaries)
  const worseBoundary = nextWorseBoundary(rating, boundaries)
  const margin = worseBoundary === null ? null : worseBoundary - attainedCii
  const marginRatio = margin === null ? null : margin / requiredCii
  const riskLevel = determineRiskLevel(rating, marginRatio)

  const basis: CalculationBasis = {
    ship_type: vessel.shipType,
    z_factor_percent: fixed.zFactorPercent,
    fuel_cf_details: details,
    a_decimal: fixed.aDecimal,
    c: fixed.c,
  }

  return {
    data: {
      attained_cii: toFixedString(attainedCii, SERIALIZATION_DIGITS.attainedCii),
      required_cii: toFixedString(requiredCii, SERIALIZATION_DIGITS.requiredCii),
      ratio_to_required: toFixedString(
        ratioToRequired,
        SERIALIZATION_DIGITS.ratioToRequired,
      ),
      estimated_rating: rating,
      next_worse_boundary_margin:
        margin === null ? null : toFixedString(margin, SERIALIZATION_DIGITS.margin),
      next_worse_boundary_margin_ratio:
        marginRatio === null
          ? null
          : toFixedString(marginRatio, SERIALIZATION_DIGITS.marginRatio),
      co2_emission_ton: toFixedString(totalCo2G / 1_000_000, SERIALIZATION_DIGITS.co2Ton),
      fuel_consumption_ton: toFixedString(totalFuelTon, SERIALIZATION_DIGITS.fuelTon),
      distance_nm: request.distance_nm,
      risk_level: riskLevel,
      transport_capacity: vessel.transportCapacity,
      transport_capacity_basis: vessel.transportCapacityBasis,
      reference_capacity: vessel.referenceCapacity,
      reference_capacity_rule: vessel.referenceCapacityRule,
      calculation_basis: basis,
    },
    parameters_used: {
      regulation_year: {
        year: String(fixed.year),
        z_factor_percent: fixed.zFactorPercent,
      },
      fuel_types: details.map((d) => ({ code: d.fuel_type, cf: d.cf })),
      reference_line: {
        ship_type: vessel.shipType,
        reference_capacity_rule: vessel.referenceCapacityRule,
        a_decimal: fixed.aDecimal,
        c: fixed.c,
      },
      rating_boundary: fixed.dVector,
      parameter_source_version: fixed.parameterSourceVersion,
    },
    calculation_run_id: '00000000-0000-4000-8000-0000000000c1',
    model_version: { ...DEMO_MODEL_VERSION },
    input_hash: DEMO_INPUT_HASH,
    parameter_hash: DEMO_PARAMETER_HASH,
    warnings: ['REFERENCE_ONLY'],
    disclaimer: DISCLAIMER,
    meta: {
      request_id: '00000000-0000-4000-8000-0000000000a1',
      timestamp: '2026-08-08T00:00:00Z',
      duration_ms: 42,
    },
  }
}

/** 요청 검증 — `API_SPEC §11` VAL 규칙. */
function validateRequest(request: VoyageCiiRequest): void {
  if (request.fuel_uses.length === 0) {
    throw new VoyageCiiError(
      'VALIDATION_ERROR',
      '연료 사용량을 1건 이상 입력해 주세요.',
      'fuel_uses',
    )
  }
  request.fuel_uses.forEach((use, index) => {
    if (!(use.fuel_ton > 0)) {
      throw new VoyageCiiError(
        'VALIDATION_ERROR',
        '연료 사용량은 0보다 커야 합니다.',
        `fuel_uses[${index}].fuel_ton`,
      )
    }
    if (!FUEL_CF[use.fuel_type]) {
      throw new VoyageCiiError(
        'UNKNOWN_FUEL_TYPE',
        `알 수 없는 연료 종류입니다: ${use.fuel_type}`,
        `fuel_uses[${index}].fuel_type`,
      )
    }
  })
  if (!(request.distance_nm > 0)) {
    throw new VoyageCiiError(
      'VALIDATION_ERROR',
      '항해거리는 0보다 커야 합니다.',
      'distance_nm',
    )
  }
  // VAL-009 — PRD §9.1이 > 0이 아니라 ≥ 1.0으로 규정한다
  if (!(request.speed_kn >= 1.0)) {
    throw new VoyageCiiError(
      'VALIDATION_ERROR',
      '속도는 1.0노트 이상이어야 합니다.',
      'speed_kn',
    )
  }
}

/**
 * 내부 계산 결과(JavaScript 숫자)를 API 형식의 십진 문자열로 직렬화한다.
 * 화면이 쓰는 `formatDecimalString()`과 달리 **문자열 생성** 쪽이다.
 */
function toFixedString(value: number, digits: number): string {
  return value.toFixed(digits)
}
