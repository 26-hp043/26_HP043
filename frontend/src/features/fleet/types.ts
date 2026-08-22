import type { Rating } from '../voyage-cii/types'

/**
 * 선대(L1) 화면의 데이터 계약 — `API_SPEC §2.8` · `UIFLOW v2.0` 2-4.
 *
 * 서버 응답(`GET /fleet/summary`)을 화면이 쓰는 형태로 옮긴 것이다. **필드를 임의로
 * 만들지 않는다** — 여기 있는 것은 전부 `#350`이 실제로 내려주는 값이다.
 */

/** 운항 상태 2축 — `PRD §3.3`. 정박·묘박 등은 모두 `NOT_UNDER_WAY`다. */
export type UnderwayState = 'UNDER_WAY' | 'NOT_UNDER_WAY'

/** 표시용 위험도 4단계 — `PRD §9.4.1`. 「지금 여유가 얼마나 있나」. */
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

/**
 * 규제 트리거 — `PRD §3.3.7`. 「MARPOL Reg 28.7에 걸렸나」.
 *
 * `riskLevel`과 **다른 것을 본다.** C등급이어도 여유가 없으면 `HIGH`지만 규제 의무는
 * 없고, D등급 3년차는 여유와 무관하게 시정조치계획 의무가 생긴다.
 */
export type RiskReason = 'E_THIS_YEAR' | 'D_THIRD_YEAR'

/**
 * 「D등급 진입까지 n일」을 내지 못한 사유 — `API_SPEC §2.8`.
 *
 * **숫자를 못 낸 것과 0일인 것은 다르다.** 서버가 `days`를 `null`로 두고 사유를 따로
 * 주는 이유이며, 화면도 그 구분을 유지한다.
 */
export type DaysReason =
  /** 이미 D 이하 — 「진입까지」가 정의되지 않는다 */
  | 'ALREADY_AT_OR_BELOW'
  /** 외삽 결과가 연말을 넘는다 */
  | 'NOT_THIS_YEAR'
  /** 정박 중 — 산정하지 않는다(값이 요동치므로) */
  | 'NOT_UNDER_WAY'
  /** 실적 또는 경계값이 없다 */
  | 'NO_DATA'

/**
 * 값을 내지 못한 사유 — `API_SPEC §2.8` (`#419`).
 *
 * **셋은 사용자가 할 일이 서로 다르다.** 항차를 등록해야 하는지, 선박 제원을
 * 채워야 하는지, 아니면 사용자가 할 수 있는 것이 없어 운영자에게 알려야 하는지가
 * 갈린다. 같은 빈칸으로 그리면 화면이 무엇을 하라고 말할 수 없다.
 */
export type UnavailableReason =
  /** 올해 집계할 항차 실적이 없다 — 항차를 등록하면 값이 나온다 */
  | 'NO_DATA'
  /** 제원으로 capacity를 정할 수 없다 — DWT·GT 부재·0 이하·미지원 선종. 선박 정보에서 고친다 */
  | 'MISSING_SPEC'
  /** 이 선종의 기준선·등급경계 파라미터가 없다 — 사용자가 할 수 있는 것이 없다 */
  | 'NO_PARAMETERS'
  /** 위 어느 것으로도 설명되지 않는 계산 실패 — 사용자가 할 수 있는 것이 없다 */
  | 'CALCULATION_ERROR'

export interface FleetVessel {
  id: string
  name: string
  shipType: string
  imoNumber: string
  underwayState: UnderwayState | null
  /** 정박·항해 세부 상태(`AT_ANCHOR` · `SAILING` 등). 상태 미기록이면 `null`. */
  detailStatus: string | null
  /** 실좌표. 미기록이면 `null` — 좌표가 없는 선박도 목록에는 나온다. */
  lat: string | null
  lon: string | null
  positionUpdatedAt: string | null
  /**
   * 서버가 내린 CII 적용 대상 판정 (`API_SPEC §2.3` · `#653`).
   * **화면이 GT로 다시 판정하지 않는다.**
   */
  isCiiApplicableHint: boolean
  /**
   * 총톤수. 판정이 아니라 **「미해당」의 원인**을 가르는 데만 쓴다 — GT가 `null`이면
   * 「대상 아님」이 아니라 「판정 불가」다.
   */
  grossTonnage: number | string | null
  /**
   * 항차 실적이 있는가. `false`면 아래 CII 값들이 전부 `null`이다.
   * **오류가 아니라 정상 상태다**(`#353` 계약).
   */
  dataAvailable: boolean
  /**
   * `dataAvailable`이 `false`인 **이유**. 값이 있으면 `null`이다 (`#419`).
   *
   * 종전에는 제원이 빠진 선박 한 척이 선대 요약 전체를 실패시켰다. 지금은 그 선박만
   * 값이 비고, 그 이유를 화면이 말할 수 있다.
   */
  unavailableReason: UnavailableReason | null
  /** 표시용 문자열 — 되돌려 계산하지 않는다(`API_SPEC §1.7`). */
  ytdAttainedCii: string | null
  ytdRequiredCii: string | null
  ytdRating: Rating | null
  riskLevel: RiskLevel | null
  riskReasons: RiskReason[]
  daysToD: number | null
  daysToDReason: DaysReason | null
}

/** 서버가 확정한 KPI. **화면이 다시 세지 않는다** — 각자 세면 어긋난다. */
export interface FleetCounts {
  total: number
  underWay: number
  notUnderWay: number
  /** 상태 미기록. 운항/정박 어느 쪽에도 넣지 않는다 — 없는 사실을 만들지 않기 위해. */
  unknownState: number
  ratingDistribution: Record<Rating, number>
  atRisk: number
  noData: number
}

/** 조치 필요 — `PRD §3.3.7` 의무. 서버가 `riskReasons`에서 파생시킨다. */
export interface FleetAction {
  vesselId: string
  vesselName: string
  severity: 'critical' | 'warning'
  reason: RiskReason
  message: string
}

export interface FleetSnapshot {
  /** `TECH_SPEC §5.4.1` 계약 ⑵ — 서버가 확정해 돌려준 기준 시각. */
  asOf: string
  regulationYear: number
  counts: FleetCounts
  vessels: FleetVessel[]
  actions: FleetAction[]
}

export interface FleetProvider {
  load(): Promise<FleetSnapshot>
}
