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

/**
 * 등급 경계 — **절대 CII 값**이다 (`#725`).
 *
 * `superior = required_cii × d1`이므로(`rating_engine`), `required_cii`로 나누면
 * 그것이 곧 `d1`~`d4`다. 등급 스케일 바는 그 비율 공간에서 그린다
 * (`components/gradeScale.ts`).
 *
 * 서버는 `#354`부터 이 값을 싣고 있었고 화면만 읽지 않았다. 네 값이 모두
 * 있어야 뜻이 있으므로 **하나라도 없으면 통째로 `null`**이다 — 셋만 있는
 * 경계로는 구간을 그릴 수 없고, 부분값은 「그릴 수 있다」로 잘못 읽힌다.
 */
export interface RatingBoundaries {
  /** A/B 경계 (`superior_boundary`) */
  superior: string
  /** B/C 경계 (`lower_boundary`) */
  lower: string
  /** C/D 경계 (`upper_boundary`) */
  upper: string
  /** D/E 경계 (`inferior_boundary`) */
  inferior: string
}

export interface YtdValues {
  dataAvailable: boolean
  attainedCii: string | null
  requiredCii: string | null
  ratioToRequired: string | null
  rating: Rating | null
  riskLevel: string | null
  marginRatio: string | null
  boundaries: RatingBoundaries | null
  totalCo2Ton: string | null
  totalFuelTon: string | null
  underwayDistanceNm: string | null
  notUnderwayDistanceNm: string | null
  totalDistanceNm: string | null
  voyageCount: number
  notUnderwayPeriodCount: number
  /**
   * 정박 구간에 기록된 연료 톤과 그 배출량 (`#1658` · `API_SPEC §2.14`).
   *
   * **「정박이 지금 등급을 밀고 있는가」의 근거다.** 구간 수만으로는 연료가 없는 구간과
   * 구분되지 않는다 — 연료가 0이면 분자가 늘지 않아 누적값이 움직이지 않는다.
   * 서버가 누적을 낼 수 없는 해는 배출량이 `null`이다.
   */
  notUnderwayFuelTon: string
  notUnderwayCo2Ton: string | null
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

/**
 * ⑶ 연말 예상이 쓴 가정 — `PRD §3.3` ⑶이 표시를 요구한다.
 *
 * `#798`에서 산출 방식이 **일평균 외삽 → 남은 거리 기반**으로 바뀌면서 필드가
 * 통째로 교체됐다. `elapsedDays`·`dailyDistanceNm`·`dailyFuelTon`·
 * `projectedExtra*`·`fuelType`은 일평균 외삽에서만 뜻이 있던 값이다.
 */
export interface ProjectionAssumptions {
  /** `REMAINING_PLAN` 고정. 종전 값은 `YTD_DAILY_AVERAGE`였다. */
  method: string
  remainingDays: string | null
  /** 더한 잔여 계획 항차 수. **0이면 ⑶이 ⑴과 같은 값이다.** */
  remainingVoyageCount: number | null
  plannedDistanceNm: string | null
  plannedCo2Ton: string | null
  completedDistanceNm: string | null
  completedCo2Ton: string | null
}

/**
 * ⑶을 무엇이 올리는가 — 시간 순 누적 분해의 한 단계 (`API_SPEC §2.14` · `#1673`).
 *
 * `key`는 `BASIS_DIFFERENCE`(확정분 집합이 갈릴 때만) · `CURRENT_VOYAGE`(진행 중 항차의
 * 남은 몫) · `REMAINING_PLAN`(남은 계획 항차) 순으로 온다. `deltaCii`의 합은 **정확히**
 * `projection.attainedCii − ytd.attainedCii`다 — 서버가 각 단계 누적값을 6자리로 절사한
 * 뒤 뺀 값이라 화면이 다시 계산하지 않는다(`TECH_SPEC §5.4.1` ⑸).
 */
interface ProjectionDriver {
  key: string
  /** 그 단계를 더했을 때 연말 예상이 움직인 양. 6자리 문자열이고 **음수일 수 있다.** */
  deltaCii: string
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
  /**
   * ⑶에만 붙는 경고 (`#798`). 최상위 `warnings`와 **범위가 다르다** — 이쪽은
   * 「이 값이 어떤 성격인가」를 말한다(예: 잔여 계획이 없어 ⑴과 같음).
   */
  warnings: string[]
  assumptions: ProjectionAssumptions | null
  /**
   * 무엇이 올리는가 (`#1673`). ⑴이 없어 출발점이 없으면 빈 배열이다 — ⑶ 전체가 계획인
   * 상태이며 「아직 안 온 값」이 아니다.
   */
  drivers: ProjectionDriver[]
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
  /**
   * 올해 누적 CII 추이 (`#1949`).
   *
   * **따로 부른다.** `/cii/current`와 한 번에 받지 않는 것은 추이가 **없어도 화면이
   * 서기 때문**이다 — 결론·재료·이번 항차는 `current` 하나로 그려지고, 추이는 그 아래
   * 블록 하나다. 한 요청으로 묶으면 추이 조회가 실패할 때 화면 전체가 오류가 된다.
   *
   * 선택 메서드다 — 검사 대역이 이 값을 흉내 내지 않아도 화면이 서야 한다.
   */
  loadSeries?(vesselId: string): Promise<YtdSeries>
  /**
   * 이번 항차의 위치와 목적항 좌표 (`#1949`).
   *
   * `/cii/current`의 `current_voyage`는 항만 **이름**만 싣는다. 좌표는 선박(`§2.1`)과
   * 항차(`§3.1`) 두 경로에 있고, R-D2(`#1672`)가 그 둘로 가라고 확정했다.
   *
   * 선택 메서드다 — 대역이 이 값을 흉내 내지 않아도 화면이 서야 한다.
   */
  loadRoute?(vesselId: string, voyageId: string): Promise<VoyageRoute>
}

/**
 * 올해 누적 CII 추이의 점 하나 (`#1671` → `#1830`).
 *
 * **점 하나 = 항차 경계 하나**다 — 일·주 단위가 아니다. 등급이 바뀐 시점은 항차
 * 경계에 있고, 이 곡선의 목적이 「언제부터 나빠지고 있나」이므로 그 시각을 찍는다.
 */
export interface YtdSeriesPoint {
  /** ISO 8601 UTC. */
  readonly at: string
  /** `ACTUAL`·`IN_PROGRESS`는 실적 쪽, `PLAN`은 계획 쪽이다. */
  readonly kind: 'ACTUAL' | 'IN_PROGRESS' | 'PLAN'
  /** 그 시각까지의 **누적** CII. 서버가 확정한 자릿수의 문자열이다 (`API_SPEC §1.7`). */
  readonly attainedCii: string
  readonly rating: string | null
  readonly voyageId: string | null
  /** 실측이 아닌 값이 섞였는가. */
  readonly substituted: boolean
}

/** 올해 누적 CII 추이 (`API_SPEC` `GET /vessels/{id}/cii/ytd-series`). */
export interface YtdSeries {
  readonly regulationYear: number
  readonly capacityBasis: CapacityBasis
  readonly requiredCii: string | null
  readonly boundaries: RatingBoundaries | null
  /** 실적 쪽 값을 낼 수 있는가. 거짓이면 계획만 있는 선박이다. */
  readonly ytdAvailable: boolean
  readonly points: readonly YtdSeriesPoint[]
  readonly asOf: string
}

/**
 * 이번 항차를 지도에 그리는 데 필요한 것 (`#1949` · R-D2 `#1672` 확정).
 *
 * **보간하지 않는다** — 진행률로 위치를 만들어 내지 않고, 서버가 마지막으로 받은
 * 위치를 그대로 찍고 **그 시각을 함께 적는다.** 값이 낡았을 수는 있어도 지어낸 것은
 * 아니라는 것이 이 화면의 약속이다.
 */
export interface VoyageRoute {
  readonly currentLat: string | null
  readonly currentLon: string | null
  /** 위치를 받은 시각. 없으면 위치가 언제 것인지 말할 수 없으므로 지도를 그리지 않는다. */
  readonly positionUpdatedAt: string | null
  readonly arrivalLat: string | null
  readonly arrivalLon: string | null
  readonly arrivalPortName: string | null
}
