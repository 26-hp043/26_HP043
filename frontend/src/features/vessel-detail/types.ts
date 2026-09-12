import type { CapacityBasis, Rating } from '../voyage-cii/types'
import type { PositionPayload } from './positionRules'

/**
 * 선박 상세(L2) 화면의 데이터 계약 — `API_SPEC §2.2` · `§2.7`.
 *
 * 두 엔드포인트를 합쳐 하나의 화면 모델로 만든다.
 *
 * - `GET /vessels/{id}` — 제원·현재 상태·위치
 * - `GET /vessels/{id}/cii-history` — 연도별 이력 + **올해 누적(YTD)**
 *
 * ## YTD를 따로 받지 않는다
 *
 * `cii-history`가 올해 행을 `status: "IN_PROGRESS"`로 함께 준다. `#354`의 3종 값
 * 엔드포인트는 **실시간 CII 화면(`#357`)** 소관이라 이 화면에는 필요하지 않다.
 * 같은 값을 두 곳에서 받으면 어느 쪽이 맞는지 판단해야 하는 상황이 생긴다.
 */

/** 연도 상태 — 확정은 연말 DCS 보고·검증 이후다(`PRD §3.3.7` 각주). */
export type YearStatus = 'CONFIRMED' | 'IN_PROGRESS'

/**
 * 한 해의 **유종 한 줄** (`#769` · `API_SPEC §2.7`).
 *
 * 비중은 **CO₂ 기준**이다 — CII의 분자가 배출량이라, 「어느 연료가 등급을 끌고
 * 있나」를 톤으로 말하면 CF가 낮은 연료를 많이 쓴 해가 실제보다 나빠 보인다.
 *
 * 배출량이 없는 해(거리 0이라 Layer 1을 타지 않은 해)는 `co2*`가 `null`이고 톤만
 * 있다. 그 해를 빼면 「정박만 한 해」가 연료축에서 통째로 사라진다.
 *
 * 내보내지 않는다 — `CiiYear` 안에서만 쓰인다(`#594` 미참조 export 규율).
 */
interface CiiYearFuel {
  fuelType: string
  /** 표시용 문자열 — 되돌려 계산하지 않는다(`API_SPEC §1.7`). */
  fuelTon: string
  co2Ton: string | null
  co2SharePercent: string | null
}

export interface CiiYear {
  regulationYear: number
  status: YearStatus
  /** `false`면 아래 수치가 전부 `null`이다. 오류가 아니라 정상 상태다. */
  dataAvailable: boolean
  /** 데이터가 없는 사유(`NO_DATA` · `NO_REGULATION_PARAMS`). */
  reason: string | null
  /** 표시용 문자열 — 되돌려 계산하지 않는다(`API_SPEC §1.7`). */
  attainedCii: string | null
  requiredCii: string | null
  rating: Rating | null
  /** **완료(실적 확정) 항차 수**다 — 진행 중 항차는 세지 않는다(`API_SPEC §2.7`). */
  voyageCount: number
  /**
   * 이 행의 거리·연료(와 CII)에 기여분이 들어간 **진행 중 항차 수**(0 또는 1 · `#800`).
   * 화면은 `voyageCountText`로 두 수를 함께 적는다(#987).
   */
  inProgressVoyageCount: number
  totalDistanceNm: string | null
  totalFuelTon: string | null
  /** 유종별 내역 (`#769`). **늘 배열이다** — 실적이 없는 해는 빈 배열. */
  fuels: CiiYearFuel[]
}

export interface VesselSpec {
  id: string
  name: string
  imoNumber: string
  shipType: string
  deadweight: string | null
  grossTonnage: string | null
  /**
   * 서버가 내린 CII 적용 대상 판정 (`API_SPEC §2.3` · `#653`).
   * **화면이 GT로 다시 판정하지 않는다.**
   */
  isCiiApplicableHint: boolean
  referenceSpeedKn: string | null
  referenceDailyFocTon: string | null
  defaultFuelType: string | null
  underwayState: 'UNDER_WAY' | 'NOT_UNDER_WAY' | null
  detailStatus: string | null
  lat: string | null
  lon: string | null
  positionUpdatedAt: string | null
}

export interface VesselDetail {
  vessel: VesselSpec
  /**
   * 표시 단위의 축. **서버가 정한다** — `DESIGN_SYSTEM §4.1`이 고정 문자열을
   * 금지하고, 화면이 선종에서 유추하면 선종이 늘 때 서버와 갈라진다.
   */
  capacityBasis: CapacityBasis
  years: CiiYear[]
  /** 확정/진행 중 판정에 쓴 기준 시각(`TECH_SPEC §5.4.1` 계약 ⑵). */
  asOf: string
}

/** 진행 중 항차의 최소 식별자 (`#588`). 링크를 그릴지 판단하는 데만 쓴다. */
export interface InProgressVoyage {
  id: string
  voyageNo: string | null
}

export interface VesselDetailProvider {
  load(vesselId: string): Promise<VesselDetail>
  /**
   * 진행 중 항차가 있는가 (`#588`).
   *
   * **`underway_state`로 판단하지 않는다.** 그 값은 「지금 무엇을 하고 있나」라는
   * 표시 상태이고, **진행 중 항차의 존재와 별개**다 — 운항 중으로 표시된 선박에
   * 항차가 없는 상태가 실제로 데이터에 있었다(`#587`). 종전에는 그 값으로 링크를
   * 그려, 눌러 들어가면 「진행 중인 항차가 없습니다」가 나왔다.
   *
   * 실시간 CII 엔드포인트(`§2.14`)를 부르지 않는다 — 그쪽은 YTD·연말 예상까지
   * 계산하므로 **링크 하나를 그리려고 치르기에는 과하다.** 항차 목록에 이미 있는
   * `status` 필터로 한 건만 묻는다.
   */
  findInProgressVoyage(vesselId: string): Promise<InProgressVoyage | null>
  /**
   * 위치·운항 상태 갱신 (`API_SPEC §2.6`).
   *
   * **갱신된 선박 객체를 돌려받아 그대로 쓴다.** `position_updated_at`은 서버가
   * 확정하므로 화면이 만들 수 없고, 만들면 단말마다 다른 시각이 표시된다.
   */
  updatePosition(vesselId: string, payload: PositionPayload): Promise<VesselSpec>
}
