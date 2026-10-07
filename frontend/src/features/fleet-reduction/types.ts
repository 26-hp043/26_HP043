/**
 * 함대 감축 계획 — `API_SPEC §2.17` · `UIFLOW 2-10` · #513.
 *
 * 수치는 **문자열 그대로** 둔다(`API_SPEC §1.7`). 화면은 표시만 한다.
 */

export type Rating = 'A' | 'B' | 'C' | 'D' | 'E'
export const TARGETS = ['NO_AT_RISK', 'ALL_C_OR_BETTER'] as const
export type Target = (typeof TARGETS)[number]

/** 감속률 상한(%) — 서버 `calc.fleet_reduction.MAX_REDUCTION_PERCENT`와 같다(`PRD §12.3.2`). */
export const MAX_REDUCTION_PERCENT = 50

export interface Adjustment {
  vesselId: string
  /** 0~50. 소수 1자리(`DESIGN_SYSTEM §4.2` 백분율) */
  percent: number
}

export interface Prices {
  /** 선박 ID → 일일 용선료(USD). 입력칸 문자열 그대로 — 비면 보내지 않는다 */
  charterUsdPerDay: Record<string, string>
  /** 유종 코드 → 연료 단가(USD/t) */
  fuelUsdPerTon: Record<string, string>
}

export interface EvaluateRequest {
  regulationYear: number
  target: Target
  adjustments: Adjustment[]
  prices: Prices
}

interface Projection {
  attainedCii: string
  rating: Rating
}

export interface VesselResult {
  vesselId: string
  vesselName: string
  /**
   * 서버가 내린 CII 적용 대상 판정 (`API_SPEC §2.17` · `§2.8`과 같은 필드 · `#2132`).
   * **화면이 GT로 다시 판정하지 않는다** — 선박명 옆 `ApplicabilityBadge`의 입력이다.
   */
  isCiiApplicableHint: boolean
  /**
   * 총톤수. 판정이 아니라 **「미해당」의 원인**을 가르는 데만 쓴다 — GT가 `null`이면
   * 「대상 아님」이 아니라 「판정 불가」다.
   */
  grossTonnage: number | string | null
  /** 계산하지 못한 선박이면 사유 — 그때 아래 필드는 `null` */
  unavailableReason: string | null
  before: Projection | null
  after: Projection | null
  targetRating: Rating | null
  meetsTarget: boolean | null
  extraDays: string | null
  fuelSavedTon: string | null
  skippedVoyages: number
  requiredCutFuelTon: string | null
  achievable: boolean | null
}

interface CostSummary {
  extraDays: string
  /** 필요한 단가가 비면 `null` — 0이 아니다 */
  charterLoss: string | null
  fuelSaving: string | null
  net: string | null
  missingCharterRates: string[]
  missingFuelPrices: string[]
}

export interface EvaluateResult {
  regulationYear: number
  target: Target
  /** 계산할 수 있는 선박이 0척이면 `null` */
  targetMet: boolean | null
  vessels: VesselResult[]
  distribution: { before: Record<Rating, number>; after: Record<Rating, number> }
  costs: CostSummary
  warnings: string[]
}

export interface SavedPlanSummary {
  planId: string
  planName: string
  regulationYear: number
  target: Target
  adjustments: Adjustment[]
  prices: Prices
  createdAt: string | null
}

export interface FleetReductionProvider {
  evaluate(request: EvaluateRequest): Promise<EvaluateResult>
  save(request: EvaluateRequest & { planName: string }): Promise<SavedPlanSummary>
  list(): Promise<SavedPlanSummary[]>
}
