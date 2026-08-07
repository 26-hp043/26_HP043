import { determineRating, determineRiskLevel, nextWorseBoundary, type Boundaries } from '../voyage-cii/rules'
import { DEMO_VESSELS, FIXED_PARAMETERS, FUEL_CF } from '../voyage-cii/referenceTable'
import type { AnnualSimulationResult, MonthlySummary } from './types'

/**
 * 기능③ 연간 시뮬레이션 demo provider (#157) — **고정값 목업이다.**
 *
 * ## 계산 엔진을 만들지 않는다
 *
 * 연간 시뮬레이션 엔진(`#63`)과 API(`#64`)는 `2026.10` 마일스톤이며 `#64`는 처리
 * 방식조차 미결이다. **이 파일은 그 결정을 선점하지 않는다.**
 *
 * 월별 (항해거리, 연료) 12쌍을 상수로 두고, 합계와 등급은 **기능①과 같은 규칙 함수**
 * (`rules.ts`)로 낸다. 합계를 따로 박아 두면 월별 행과 어긋날 수 있고, 목업이
 * 스스로 모순되면 시연에서 그것이 먼저 눈에 띈다.
 *
 * **CII 산식은 새로 쓰지 않았다** — `M / (capacity × distance)`는 `PRD §13.1`의
 * 정의이며 기능① demo provider가 이미 쓰는 식이다. 연간은 그 분자·분모를 합으로
 * 바꾼 것뿐이다.
 *
 * ## 확률을 내지 않는다
 *
 * `types.ts` 주석 참조 — `P(D∪E)`의 계산 정의가 `PRD`에 없다(`#170` ⑶).
 *
 * ## 값의 성격
 *
 * 아래 월별 상수는 **시연용으로 지어낸 값이다.** 실측도 추정 모델의 출력도 아니다.
 * 응답의 `is_sample_data`가 `true`인 것이 그 사실이며, 화면은 그 플래그를 보고
 * 「예시 데이터」 배지를 띄운다.
 */

/** 시연 대상 — 기능①·②와 같은 선박이라 세 화면이 이어져 읽힌다. */
const DEMO_VESSEL_ID = '00000000-0000-4000-8000-000000000001'
const DEMO_YEAR = 2026
const DEMO_FUEL = 'HFO'

/** 월별 (항해거리 nm, 연료 t) — 시연용 상수. */
const MONTHLY_INPUT: ReadonlyArray<{ month: string; voyages: number; distanceNm: number; fuelTon: number }> = [
  { month: '2026-01', voyages: 3, distanceNm: 4200, fuelTon: 330 },
  { month: '2026-02', voyages: 2, distanceNm: 3800, fuelTon: 312 },
  { month: '2026-03', voyages: 3, distanceNm: 4500, fuelTon: 352 },
  { month: '2026-04', voyages: 3, distanceNm: 4100, fuelTon: 340 },
  { month: '2026-05', voyages: 4, distanceNm: 4700, fuelTon: 368 },
  { month: '2026-06', voyages: 3, distanceNm: 3900, fuelTon: 318 },
]

/** `PRD §6.3` 「모든 결과 화면」 문구. */
const DISCLAIMER = '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.'

/** 기능① provider와 같은 직렬화 자릿수. */
const DIGITS = {
  cii: 6,
  ton: 2,
  ratio: 5,
} as const

export interface AnnualSimulationProvider {
  load(): Promise<AnnualSimulationResult>
}

export function createDemoAnnualProvider(): AnnualSimulationProvider {
  return {
    async load() {
      return buildResult()
    },
  }
}

function buildResult(): AnnualSimulationResult {
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

  const months: MonthlySummary[] = MONTHLY_INPUT.map((row) => {
    const co2Ton = row.fuelTon * cf
    return {
      month: row.month,
      voyage_count: row.voyages,
      distance_nm: row.distanceNm,
      fuel_ton: row.fuelTon.toFixed(DIGITS.ton),
      co2_emission_ton: co2Ton.toFixed(DIGITS.ton),
      attained_cii: ((co2Ton * 1_000_000) / (capacity * row.distanceNm)).toFixed(DIGITS.cii),
    }
  })

  const totalDistance = MONTHLY_INPUT.reduce((sum, r) => sum + r.distanceNm, 0)
  const totalFuel = MONTHLY_INPUT.reduce((sum, r) => sum + r.fuelTon, 0)
  const totalCo2Ton = totalFuel * cf
  const attainedCii = (totalCo2Ton * 1_000_000) / (capacity * totalDistance)

  const requiredCii = Number(fixed.requiredCii)
  const boundaries: Boundaries = {
    superior: Number(fixed.boundaries.superior),
    lower: Number(fixed.boundaries.lower),
    upper: Number(fixed.boundaries.upper),
    inferior: Number(fixed.boundaries.inferior),
  }

  const rating = determineRating(attainedCii, boundaries)
  const worseBoundary = nextWorseBoundary(rating, boundaries)
  const marginRatio =
    worseBoundary === null ? null : (worseBoundary - attainedCii) / requiredCii

  return {
    vessel_display_name: vessel.displayName,
    ship_type: vessel.shipType,
    regulation_year: DEMO_YEAR,
    transport_capacity_basis: vessel.transportCapacityBasis,
    required_cii: requiredCii.toFixed(DIGITS.cii),
    attained_cii: attainedCii.toFixed(DIGITS.cii),
    ratio_to_required: (attainedCii / requiredCii).toFixed(DIGITS.ratio),
    estimated_rating: rating,
    risk_level: determineRiskLevel(rating, marginRatio),
    next_worse_boundary_margin_ratio:
      marginRatio === null ? null : marginRatio.toFixed(DIGITS.ratio),
    total_distance_nm: totalDistance,
    total_fuel_ton: totalFuel.toFixed(DIGITS.ton),
    total_co2_emission_ton: totalCo2Ton.toFixed(DIGITS.ton),
    months,
    warnings: ['REFERENCE_ONLY'],
    disclaimer: DISCLAIMER,
    is_sample_data: true,
  }
}
