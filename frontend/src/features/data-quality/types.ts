/**
 * 데이터 점검 — `GET /fleet/data-quality` (`API_SPEC §2.16` · `UIFLOW 2-11` · #513).
 *
 * 수치는 **문자열 그대로** 둔다(`API_SPEC §1.7`). 화면은 표시만 한다.
 */

/** `DESIGN_SYSTEM §2.3.1` 표 순서 — 서버가 이 순서로 정렬해 준다. */
export const SEVERITIES = [
  'SUBSTITUTED',
  'UNAVAILABLE',
  'ANOMALY',
  'UNCONFIRMED',
  'PUBLIC_RECORD',
] as const
export type Severity = (typeof SEVERITIES)[number]

export type Rating = 'A' | 'B' | 'C' | 'D' | 'E'

/** 그 항차를 뺀 누적 CII와의 차이 (`PRD §17.4.2`). */
interface CiiImpact {
  attainedCii: string
  attainedCiiWithout: string
  /** 누적 − 뺀 누적. **양수면 이 항차가 누적 CII를 높이고 있다** */
  delta: string
  rating: Rating | null
  ratingWithout: Rating | null
}

/** `public_record.mismatches[].field` — 넣은 값이 공적 기록과 어긋난 시각 종류. */
export type PublicRecordField = 'DEPARTURE' | 'ARRIVAL' | 'BERTH_START' | 'BERTH_END'

/** 공적 기록 한 항목과의 어긋남 (`API_SPEC §2.16` `public_record.mismatches` · #1197). */
export interface PublicRecordMismatch {
  field: PublicRecordField
  enteredAt: string
  recordedAt: string
  differenceMinutes: number
  portAuthorityCode: string
  /** 항만청 코드만 있고 이름이 없을 수 있다 */
  portAuthorityName: string | null
  /*
   * 「이 값으로 채우기」(`API_SPEC §3.12` · #1923)의 재료 — 어느 기항의 시각인가. 옛 서버는
   * 필드 자체가 없어 `null`이다. 그때는 채우기 버튼을 두지 않는다(보낼 열쇠가 없다).
   */
  callYear: number | null
  callSeq: string | null
  /** 정박 칸이면 그 구간 id. 항차 칸은 `null` */
  periodId: string | null
}

/** 공적 재항 기록 대조 — `PUBLIC_RECORD` 행에만 있다(그 외는 `null`). */
export interface PublicRecord {
  source: string
  fetchedAt: string
  /** 그 항차의 상태 — `CONFIRMED`면 채우기 전에 확정을 되돌린다고 한 번 더 묻는다 (#1923) */
  voyageStatus: string | null
  mismatches: PublicRecordMismatch[]
}

/** `POST /voyages/{id}/public-record-fill` 요청 (`API_SPEC §3.12` · #1923). */
export interface PublicRecordFillRequest {
  field: PublicRecordField
  periodId: string | null
  record: { source: string; portAuthorityCode: string; callYear: number; callSeq: string }
  /** 화면이 사용자에게 보인 공적 기록 시각 — 서버가 다시 읽은 값과 다르면 409 */
  recordedAt: string
  /** 확정 항차를 되돌리는 데 사용자가 동의했다(재확인 줄을 통과했다) */
  revertConfirmed: boolean
}

/** 채운 결과 — 화면은 다시 불러오고 한 줄로 알린다. */
export interface PublicRecordFillResult {
  field: PublicRecordField
  /** 확정을 되돌렸으면 `'CONFIRMED'` */
  revertedFromStatus: string | null
}

export interface DataQualityIssue {
  severity: Severity
  vesselId: string
  vesselName: string
  /** 선박 단위 문제(계산 불가)면 `null` */
  voyageId: string | null
  voyageNo: string | null
  /** 사유 코드 — 대체 `FUEL:HFO`·`DISTANCE` · 이상치 `FUEL_VS_MODEL` · 공적 기록 `PUBLIC_RECORD:ARRIVAL` 등 */
  codes: string[]
  cii: CiiImpact | null
  /** `cii`가 `null`인 이유. 선박 단위 문제면 이것도 `null` */
  ciiReason: string | null
  /** `PUBLIC_RECORD` 행이 아니면 `null` — 완결성 계산에는 들어가지 않는다 */
  publicRecord: PublicRecord | null
}

/**
 * 완결성 비율의 분자·분모와 제외 내역 (`API_SPEC §2.16` · #1532). CO₂ 톤 문자열(소수 2자리).
 * `measured + Σexcluded = total` — 한 항차는 한 축에만 더해진다(계산 불가 > 대체 계산 > 이상치).
 */
export interface CompletenessBreakdown {
  totalCo2Ton: string
  measuredCo2Ton: string
  excludedUnavailableCo2Ton: string
  excludedSubstitutedCo2Ton: string
  excludedAnomalyCo2Ton: string
}

interface DataQualityVessel {
  vesselId: string
  vesselName: string
  dataAvailable: boolean
  unavailableReason: string | null
  ytdAttainedCii: string | null
  ytdRating: Rating | null
  voyageCount: number
  /** 0~1 비율 문자열. 배출이 없거나 계산할 수 없으면 `null` */
  completenessRatio: string | null
  /** 비율의 내역 — `completenessRatio`와 같은 조건에서 `null`. 화면 표시는 아직 없다(#1532 후속) */
  completeness?: CompletenessBreakdown | null
}

export interface DataQualitySnapshot {
  regulationYear: number
  counts: Record<Severity, number>
  /** 이상치를 **판정하지 못한** 항차 수 — 0건과 섞지 않는다 */
  anomalyUnjudged: number
  completenessRatio: string | null
  /** 선대 합의 내역 — 낼 수 있는 선박들의 분자·분모를 각각 더한 것 */
  completeness?: CompletenessBreakdown
  vessels: DataQualityVessel[]
  issues: DataQualityIssue[]
}

export interface DataQualityProvider {
  load(regulationYear?: number): Promise<DataQualitySnapshot>
  /**
   * 「이 값으로 채우기」 (#1923). **없으면 버튼을 그리지 않는다** — 읽기만 하는 대역·옛
   * 조립에서 누를 수 없는 버튼을 보이지 않게.
   */
  fill?(voyageId: string, request: PublicRecordFillRequest): Promise<PublicRecordFillResult>
}
