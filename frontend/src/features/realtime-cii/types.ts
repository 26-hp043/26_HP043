/**
 * 실시간 CII 화면 타입 — `API_SPEC §2.14` (`#357`).
 *
 * ## 수치를 문자열로 둔다
 *
 * `API_SPEC §1.7`이 계산 결과를 문자열로 직렬화한다. `parseFloat`으로 되돌리면
 * Layer 1이 `Decimal`로 지킨 정밀도가 사라진다. 화면은 표시만 하므로 문자열
 * 그대로가 맞고, **비교가 필요한 곳에서만** 그 자리에서 숫자로 읽는다.
 */

export type Rating = 'A' | 'B' | 'C' | 'D' | 'E'
export type CapacityBasis = 'DWT' | 'GT'

/** ⑴ 연간 누적 — **등급이 붙는 유일한 값**(`PRD §3.3` 표). */
/**
 * 실적 대신 계획값을 쓴 내역 — `API_SPEC §2.14` (`#449`).
 *
 * `PRD §8.3` 값 우선순위가 실적이 없을 때 계획값을 고르는데, 그 **선택 결과**를
 * 항차별로 싣는다. 경고(`COMPLETED_NO_FUEL`)는 「대체가 있었다」만 말하므로
 * **무엇을 고쳐야 하는지**는 이 목록이 있어야 나온다.
 */
export interface Substitution {
  voyageId: string
  /** 대체된 축. 거리는 CII의 분모라 영향이 연료 못지않다. */
  axis: 'FUEL' | 'DISTANCE'
  /** 연료 축일 때 유종. 거리 축이면 `null`. */
  fuelType: string | null
}

export interface YtdValues {
  dataAvailable: boolean
  attainedCii: string | null
  requiredCii: string | null
  ratioToRequired: string | null
  rating: Rating | null
  riskLevel: string | null
  marginRatio: string | null
  totalCo2Ton: string | null
  totalFuelTon: string | null
  underwayDistanceNm: string | null
  notUnderwayDistanceNm: string | null
  totalDistanceNm: string | null
  voyageCount: number
  notUnderwayPeriodCount: number
  /** 비어 있으면 전부 실측이다 (`§2.14`). */
  substitutions: Substitution[]
}

/**
 * ⑵ 항차 구간값 — **등급이 없다**(`COR-1`).
 *
 * `rating`을 optional로 두지 않고 `null`로 고정한 것은 의도다. 서버가 명시적으로
 * `null`을 싣고, 타입도 그 계약을 그대로 적는다 — 나중에 누군가 여기에 등급을
 * 채우려 하면 타입에서 막힌다.
 */
export interface VoyageSegment {
  voyageId: string
  voyageNo: string | null
  status: string
  departurePortName: string | null
  arrivalPortName: string | null
  plannedDistanceNm: string | null
  underwayHours: string | null
  distanceNm: string | null
  fuelTon: string | null
  fuelType: string | null
  isSimulated: boolean
  attainedCii: string | null
  co2Ton: string | null
  rating: null
}

/** ⑶ 연말 예상이 쓴 가정 — `PRD §3.3` ⑶이 표시를 요구한다. */
export interface ProjectionAssumptions {
  method: string
  elapsedDays: string | null
  remainingDays: string | null
  dailyDistanceNm: string | null
  dailyFuelTon: string | null
  projectedExtraDistanceNm: string | null
  projectedExtraFuelTon: string | null
  fuelType: string | null
}

/** ⑶ 연말 예상. 낼 수 없으면 `reason`이 이유를 말한다. */
export interface YearEndProjection {
  dataAvailable: boolean
  reason: string | null
  attainedCii: string | null
  requiredCii: string | null
  ratioToRequired: string | null
  rating: Rating | null
  riskLevel: string | null
  assumptions: ProjectionAssumptions | null
}

export interface RealtimeCii {
  vesselId: string
  vesselName: string
  regulationYear: number
  capacityBasis: CapacityBasis
  underwayState: 'UNDER_WAY' | 'NOT_UNDER_WAY' | null
  ytd: YtdValues
  /** 진행 중 항차가 없으면 `null`. 오류가 아니다. */
  currentVoyage: VoyageSegment | null
  projection: YearEndProjection
  warnings: string[]
  /** 서버가 확정한 기준 시각. 이 값으로 다시 물으면 같은 결과가 나온다. */
  asOf: string
  /** `PRD R-5` 「시뮬레이션 데이터」 배지의 근거. **서버가 판정한다.** */
  simulated: boolean
}

export interface RealtimeCiiProvider {
  load(vesselId: string): Promise<RealtimeCii>
}
