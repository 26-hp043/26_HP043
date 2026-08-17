import { DEMO_VESSELS, FIXED_PARAMETERS, FUEL_CF } from '../voyage-cii/referenceTable'
import { determineRating, type Boundaries } from '../voyage-cii/rules'
import type { Rating } from '../voyage-cii/types'
import type {
  AnnualSimulationProvider,
  AnnualSimulationRequest,
  AnnualSimulationResult,
} from './types'

/**
 * 기능③ demo provider — **고정값 목업이다** (#157 · #442에서 계약 갱신).
 *
 * ## 왜 남겨 두는가
 *
 * 실 API가 붙은 뒤에도 **백엔드를 띄우지 않고 화면만 보는 상황**이 남는다(디자인 검토·
 * 프론트엔드 리팩터링). `#138`이 기능①에서 같은 판단을 했다.
 *
 * ## 서버 계약을 그대로 흉내 낸다
 *
 * v1은 월별 집계 12행을 담았는데 **서버는 그것을 주지 않는다.** demo가 서버와 다른
 * 모양을 내면 화면이 두 형태를 모두 다뤄야 하고, 그 분기가 곧 버그 자리가 된다. 그래서
 * `#64` 응답과 **같은 블록**(결정론·Monte Carlo·민감도·스냅샷)을 낸다.
 *
 * ## 확률을 「계산」하지 않는다
 *
 * Monte Carlo를 화면에서 돌리지 않는다 — 그건 서버 소관이고(`PRD §12.4`), 여기서 돌리면
 * **같은 화면의 demo와 실 API가 다른 난수 계열**을 쓰게 된다. 등급별 확률은 **시연용
 * 고정 분포**이며 합이 1이 되도록만 맞춘다. `is_sample_data: true`가 그 사실을 알린다.
 *
 * ## 값의 성격
 *
 * 아래 상수는 **시연용으로 지어낸 값이다.** 실측도 추정 모델의 출력도 아니다.
 */

/** 시연 대상 — 기능①·②와 같은 선박이라 세 화면이 이어져 읽힌다. */
const DEMO_VESSEL_ID = '00000000-0000-4000-8000-000000000001'
const DEMO_YEAR = 2026
const DEMO_FUEL = 'HFO'

/** 시연용 누적 실적·잔여 계획 (항해거리 nm, 연료 t). */
const COMPLETED = { voyages: 8, distanceNm: 25200, fuelTon: 2020 }
const REMAINING = { voyages: 4, distanceNm: 12600, fuelTon: 1010 }

/**
 * 시연용 등급별 확률 — 합 1.0000.
 *
 * 결정론 예측 등급 근처에 무게가 실리도록 잡았다. **모델의 출력이 아니다.**
 */
const DEMO_PROBABILITIES: Record<Rating, string> = {
  A: '0.0200',
  B: '0.2800',
  C: '0.5500',
  D: '0.1300',
  E: '0.0200',
}

const DIGITS = { cii: 6, gco2: 0, capacity: 0 } as const

export function createDemoAnnualProvider(): AnnualSimulationProvider {
  return {
    async run(request: AnnualSimulationRequest) {
      return buildResult(request)
    },
  }
}

function buildResult(request: AnnualSimulationRequest): AnnualSimulationResult {
  const vessel = DEMO_VESSELS.find((v) => v.id === DEMO_VESSEL_ID)
  const fixed = FIXED_PARAMETERS.find(
    (p) => p.vesselId === DEMO_VESSEL_ID && p.year === DEMO_YEAR,
  )
  if (!vessel || !fixed) {
    // 고정표에서 선박·연도가 사라지면 조용히 빈 화면을 내지 않는다.
    throw new Error('데모 고정표에 대상 선박·연도가 없습니다.')
  }

  const cf = Number(FUEL_CF[DEMO_FUEL].cf)
  const capacity = Number(vessel.transportCapacity)

  // `PRD §12.3` — 분자는 누적 + 잔여, 분모도 같은 방식으로 더한다.
  const completedM = COMPLETED.fuelTon * cf * 1_000_000
  const plannedM = REMAINING.fuelTon * cf * 1_000_000
  const completedW = capacity * COMPLETED.distanceNm
  const plannedW = capacity * REMAINING.distanceNm
  const projected = (completedM + plannedM) / (completedW + plannedW)

  //
  // 경계는 **고정표가 담고 있는 값을 그대로 쓴다.** `requiredCii × d`로 다시 만들면
  // 표시 자릿수로 잘린 값에서 곱해져 경계에 걸린 등급이 갈릴 수 있다(`referenceTable`
  // 주석이 같은 경고를 적는다).
  //
  const boundaries: Boundaries = {
    superior: Number(fixed.boundaries.superior),
    lower: Number(fixed.boundaries.lower),
    upper: Number(fixed.boundaries.upper),
    inferior: Number(fixed.boundaries.inferior),
  }
  const rating = determineRating(projected, boundaries)

  return {
    simulation_id: '00000000-0000-4000-8000-0000000000f3',
    calculation_run_id: '00000000-0000-4000-8000-0000000000f4',
    deterministic: {
      projected_attained_cii: projected.toFixed(DIGITS.cii),
      projected_rating: rating,
      completed_voyage_count: COMPLETED.voyages,
      remaining_voyage_count: REMAINING.voyages,
      completed_M_gco2: completedM.toFixed(DIGITS.gco2),
      completed_W_capacity_nm: completedW.toFixed(DIGITS.capacity),
      planned_M_gco2: plannedM.toFixed(DIGITS.gco2),
      planned_W_capacity_nm: plannedW.toFixed(DIGITS.capacity),
    },
    monte_carlo: {
      rng_metadata: {
        // 데모임을 seed에서도 알 수 있게 한다 — 실 API의 128-bit hex와 형태가 다르다.
        seed_entropy: 'demo-fixed',
        bit_generator: 'DEMO_FIXED',
        numpy_version: '-',
        python_version: '-',
        platform: 'demo',
      },
      runs: request.simulation_runs,
      rating_probabilities: DEMO_PROBABILITIES,
      target_success_probability: successProbability(request.target_rating),
      target_rating: request.target_rating,
      p10: (projected * 0.94).toFixed(DIGITS.cii),
      p50: projected.toFixed(DIGITS.cii),
      p90: (projected * 1.07).toFixed(DIGITS.cii),
      mean_cii: projected.toFixed(DIGITS.cii),
    },
    // `PRD §9.4.2` 확률 기반. demo도 서버와 같은 규칙을 쓴다.
    risk_level: 'HIGH',
    sensitivity_analysis: {
      interaction_note: '각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다.',
      speed_minus_1kn: {
        projected_cii: (projected * 0.965).toFixed(DIGITS.cii),
        rating_change: `${rating}→${rating}`,
        target_probability_change: '+0.12',
      },
      speed_plus_1kn: {
        projected_cii: (projected * 1.038).toFixed(DIGITS.cii),
        rating_change: `${rating}→${rating}`,
        target_probability_change: '-0.08',
      },
      fuel_minus_10pct: {
        projected_cii: (projected * 0.95).toFixed(DIGITS.cii),
        rating_change: `${rating}→${rating}`,
        target_probability_change: '+0.10',
      },
      fuel_plus_10pct: {
        projected_cii: (projected * 1.05).toFixed(DIGITS.cii),
        rating_change: `${rating}→${rating}`,
        target_probability_change: '-0.06',
      },
    },
    snapshot: {
      snapshot_id: '00000000-0000-4000-8000-0000000000f5',
      created_at: '2026-08-17T00:00:00+00:00',
      voyage_count: COMPLETED.voyages + REMAINING.voyages,
    },
    warnings: ['REFERENCE_ONLY'],
    is_sample_data: true,
  }
}

/**
 * 목표 등급 **이상**을 달성할 확률 — 고정 분포에서 누적한다.
 *
 * `PRD §12.5`의 「목표 등급 이상」 정의를 따른다. demo가 목표에 따라 값을 바꾸지 않으면
 * 목표를 고르는 입력이 화면에서 아무 일도 하지 않는 것처럼 보인다.
 */
function successProbability(target: Rating): string {
  const order: Rating[] = ['A', 'B', 'C', 'D', 'E']
  const upTo = order.slice(0, order.indexOf(target) + 1)
  const sum = upTo.reduce((acc, r) => acc + Number(DEMO_PROBABILITIES[r]), 0)
  return sum.toFixed(4)
}
