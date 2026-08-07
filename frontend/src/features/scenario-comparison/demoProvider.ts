import { createDemoProvider } from '../voyage-cii/demoProvider'
import { findVessel } from '../voyage-cii/referenceTable'
import { ScenarioComparisonError, type ScenarioComparisonProvider } from './provider'
import type {
  ScenarioComparisonRequest,
  ScenarioComparisonResponse,
  ScenarioResult,
  ScenarioType,
} from './types'

/**
 * 기능② demo provider (#156).
 *
 * ## 계산을 새로 구현하지 않는다
 *
 * 시나리오마다 **기능① demo provider(`#134`)의 `estimate()`를 호출**한다.
 * CII·등급·위험도 산정을 여기서 다시 쓰면 두 화면이 서로 다른 값을 낼 수 있고,
 * 그 차이는 시연 중에야 드러난다. 같은 엔진을 통과시키면 그 위험이 없다.
 *
 * 부수 효과로 `#39`(등급)·`#40`(위험도)가 머지될 때 대조 지점이 하나로 남는다.
 *
 * ## 연료량은 시나리오별 고정값이다
 *
 * 속력에서 연료를 산정하는 모델(cubic speed model, `#75`)은 **백엔드 소관**이며
 * 8/8 범위 밖이다. 프론트엔드가 계산 원리를 알 필요가 없으므로 아래 표에 값을
 * 박아 두고, `#57` 연결 시 이 파일이 통째로 `apiScenarioProvider`로 교체된다.
 *
 * ## 시나리오 생성 방식 — `PRD §11.2`
 *
 * | 시나리오 | 생성 |
 * |---|---|
 * | `DIRECT` | 입력 그대로 |
 * | `DETOUR` | **거리 +5%** — 「기상 회피 또는 운항상 이유로 거리 증가. 기본 +5%」 |
 * | `SLOW_STEAMING` | **속력 −1 kn**, floor `max(speed − 1, 1.0)` |
 *
 * **`DETOUR`의 연료 증가율(+10%)이 거리 증가율(+5%)보다 크다.** 우회하는 이유가
 * 기상이고 그 조건에서 소모가 늘기 때문이다. 실제 산정은 `#75` 소관이며 이 값은
 * 시연용 상수다.
 */

/** `PRD §11.2` 기본 우회율. */
const DETOUR_DISTANCE_RATIO = 1.05

/** `PRD §11.2` 기본 감속량(kn)과 속력 하한. */
const SLOW_STEAMING_SPEED_DELTA = 1.0
const MIN_SPEED_KN = 1.0

/**
 * 시나리오별 연료 배수 — **시연용 상수다.**
 * `#75`(cubic speed model)가 확정되면 이 표는 사라진다.
 */
const FUEL_RATIO: Readonly<Record<ScenarioType, number>> = {
  DIRECT: 1.0,
  /** 거리 +5%에 기상 조건에 의한 소모 증가를 더한 값 */
  DETOUR: 1.1,
  /** 14 → 13 kn 감속의 시연용 값 */
  SLOW_STEAMING: 0.8625,
}

const SCENARIO_NAME: Readonly<Record<ScenarioType, string>> = {
  DIRECT: '직항',
  DETOUR: '우회',
  SLOW_STEAMING: '감속',
}

/** `PRD §6.3` — 「자동 결정 금지」 행의 문구를 그대로 복사했다. */
export const NO_AUTO_DECISION_NOTICE =
  '시스템은 시나리오별 수치만 비교하며, 최종 운항 판단은 사용자에게 있습니다.'

/** `PRD §6.3` — 「추정값 사용」 행. */
export const ESTIMATE_NOTICE = '일부 값은 사용자 입력 또는 모델 추정값입니다.'

export function createDemoScenarioProvider(): ScenarioComparisonProvider {
  const voyageProvider = createDemoProvider()

  return {
    async compare(request) {
      return compareScenarios(request, voyageProvider.estimate)
    },
  }
}

type Estimate = ReturnType<typeof createDemoProvider>['estimate']

async function compareScenarios(
  request: ScenarioComparisonRequest,
  estimate: Estimate,
): Promise<ScenarioComparisonResponse> {
  validate(request)

  const vessel = findVessel(request.vessel_id)
  if (!vessel) {
    throw new ScenarioComparisonError(
      'UNSUPPORTED_VESSEL',
      '지원하지 않는 선박입니다.',
      'vessel_id',
    )
  }

  const plans = buildPlans(request)

  const results: ScenarioResult[] = []
  let requiredCii = ''
  let basis = vessel.transportCapacityBasis
  let shipType = vessel.shipType
  let warnings: string[] = []
  let disclaimer = ''

  for (const plan of plans) {
    // 기능①과 같은 엔진을 통과시킨다. 여기서 오류가 나면 기능①에서도 난다.
    const response = await estimate({
      vessel_id: request.vessel_id,
      regulation_year: request.regulation_year,
      distance_nm: plan.distanceNm,
      speed_kn: plan.speedKn,
      fuel_uses: [{ fuel_type: request.fuel_type, fuel_ton: plan.fuelTon }],
    }).catch((error: unknown) => {
      throw toScenarioError(error)
    })

    const data = response.data
    requiredCii = data.required_cii
    basis = data.transport_capacity_basis
    shipType = data.calculation_basis.ship_type
    warnings = response.warnings
    disclaimer = response.disclaimer

    results.push({
      scenario_type: plan.type,
      scenario_name: SCENARIO_NAME[plan.type],
      distance_nm: plan.distanceNm,
      speed_kn: plan.speedKn,
      duration_hours: serializeHours(plan.distanceNm / plan.speedKn),
      fuel_ton: data.fuel_consumption_ton,
      co2_emission_ton: data.co2_emission_ton,
      attained_cii: data.attained_cii,
      ratio_to_required: data.ratio_to_required,
      estimated_rating: data.estimated_rating,
      risk_level: data.risk_level,
      next_worse_boundary_margin_ratio: data.next_worse_boundary_margin_ratio,
    })
  }

  return {
    scenarios: results,
    required_cii: requiredCii,
    transport_capacity_basis: basis,
    ship_type: shipType,
    vessel_display_name: vessel.displayName,
    warnings,
    disclaimer,
  }
}

interface ScenarioPlan {
  type: ScenarioType
  distanceNm: number
  speedKn: number
  fuelTon: number
}

/** `PRD §11.2` 생성 방식. 순서도 그 표를 따른다. */
function buildPlans(request: ScenarioComparisonRequest): ScenarioPlan[] {
  const { base_distance_nm: distance, base_speed_kn: speed, base_fuel_ton: fuel } = request

  return [
    {
      type: 'DIRECT',
      distanceNm: distance,
      speedKn: speed,
      fuelTon: round2(fuel * FUEL_RATIO.DIRECT),
    },
    {
      type: 'DETOUR',
      distanceNm: round2(distance * DETOUR_DISTANCE_RATIO),
      speedKn: speed,
      fuelTon: round2(fuel * FUEL_RATIO.DETOUR),
    },
    {
      type: 'SLOW_STEAMING',
      distanceNm: distance,
      // floor 를 두지 않으면 1.0 kn 입력에서 0 kn 이 되어 소요 시간이 무한이 된다.
      speedKn: Math.max(speed - SLOW_STEAMING_SPEED_DELTA, MIN_SPEED_KN),
      fuelTon: round2(fuel * FUEL_RATIO.SLOW_STEAMING),
    },
  ]
}

/** 부동소수점 잔여 자릿수를 남기지 않는다 — `80 * 1.1 = 88.00000000000001`. */
function round2(value: number): number {
  return Math.round(value * 100) / 100
}

/**
 * 소요 시간 직렬화.
 *
 * `DESIGN_SYSTEM §4.2`가 표시 자릿수를 1로 정하지만 **여기서 1자리로 자르지 않는다** —
 * 「내부에는 원본 값을 보관하고 반올림은 표시 시점에만」(`§4.2` 반올림 🔒).
 * 기능① provider의 직렬화 자릿수 관행에 맞춰 넉넉히 남긴다.
 */
function serializeHours(value: number): string {
  return value.toFixed(4)
}

function validate(request: ScenarioComparisonRequest): void {
  if (!(request.base_distance_nm > 0)) {
    throw new ScenarioComparisonError(
      'VALIDATION_ERROR',
      '항해거리는 0보다 커야 합니다.',
      'base_distance_nm',
    )
  }
  // VAL-009 — PRD §9.1이 > 0이 아니라 ≥ 1.0으로 규정한다
  if (!(request.base_speed_kn >= MIN_SPEED_KN)) {
    throw new ScenarioComparisonError(
      'VALIDATION_ERROR',
      '속도는 1.0노트 이상이어야 합니다.',
      'base_speed_kn',
    )
  }
  if (!(request.base_fuel_ton > 0)) {
    throw new ScenarioComparisonError(
      'VALIDATION_ERROR',
      '연료 사용량은 0보다 커야 합니다.',
      'base_fuel_ton',
    )
  }
}

/** 기능① provider 오류를 기능② 오류로 옮긴다. 화면이 두 타입을 알지 않게 한다. */
function toScenarioError(error: unknown): ScenarioComparisonError {
  if (error instanceof ScenarioComparisonError) return error
  const message = error instanceof Error ? error.message : '계산에 실패했습니다.'
  const code = (error as { code?: string } | null)?.code
  if (
    code === 'UNSUPPORTED_VESSEL' ||
    code === 'UNSUPPORTED_YEAR' ||
    code === 'UNKNOWN_FUEL_TYPE' ||
    code === 'VALIDATION_ERROR' ||
    code === 'CALCULATION_ERROR'
  ) {
    return new ScenarioComparisonError(code, message)
  }
  return new ScenarioComparisonError('CALCULATION_ERROR', message)
}
