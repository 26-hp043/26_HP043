import { SESSION_EXPIRED_MESSAGE, redirectToLogin } from '../../auth/session'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'

/**
 * 선박 상세의 **계산 이력** (#992 · `API_SPEC §1.9` · `PRD §8.4` 「재계산 필요 표시」).
 *
 * `GET /calculations`는 서버에 있었는데 화면에서 닿을 수 없었다(`#556` → `#776` 「범위 밖」 →
 * 2026-09-11 결정 3-② 「범위 밖은 없다」). 그사이 `needs_recalc`가 실제로 켜지게 됐다 —
 * 선박 제원 변경(`#283`·`#944`)과 항차 계획 변경(`#817` 귀속)이 켠다. 그 표시를 **보는 자리**다.
 */

type CalculationType =
  | 'VOYAGE_ESTIMATE'
  | 'SCENARIO'
  | 'ANNUAL_DETERMINISTIC'
  | 'ANNUAL_MONTE_CARLO'

/** 계산 종류 — 사용자가 아는 화면 이름으로 부른다(`screens.ts` 라벨과 같은 말). */
const CALCULATION_TYPE_LABELS: Record<CalculationType, string> = {
  VOYAGE_ESTIMATE: 'CII 예측',
  SCENARIO: '항로 비교',
  ANNUAL_DETERMINISTIC: '연간 시뮬레이션',
  ANNUAL_MONTE_CARLO: '연간 시뮬레이션',
}

export interface CalculationRow {
  id: string
  type: string
  typeLabel: string
  createdAt: string
  /** 표시용 — 소수 3자리(`DESIGN_SYSTEM §4.1`). 요약이 없는 종류는 `—`. */
  ciiText: string
  rating: string | null
  /** 항차에 붙은 계산인가 (`#817`). */
  attachedToVoyage: boolean
  needsRecalc: boolean
}

interface CalculationPage {
  rows: CalculationRow[]
  nextCursor: string | null
  hasMore: boolean
}

interface ServerRun {
  calculation_run_id: string
  calculation_type: string
  voyage_id: string | null
  result_summary?: { attained_cii?: string; estimated_rating?: string }
  needs_recalc: boolean
  created_at: string
}

/** 서버 행 → 화면 행. 요약은 기능① 계산만 싣는다(`API_SPEC §1.9` `result_summary`). */
export function toCalculationRow(raw: ServerRun): CalculationRow {
  const cii = raw.result_summary?.attained_cii
  return {
    id: raw.calculation_run_id,
    type: raw.calculation_type,
    typeLabel: CALCULATION_TYPE_LABELS[raw.calculation_type as CalculationType] ?? raw.calculation_type,
    createdAt: raw.created_at,
    ciiText: cii ? formatDecimalString(cii, DISPLAY_DIGITS.cii) : '—',
    rating: raw.result_summary?.estimated_rating ?? null,
    attachedToVoyage: raw.voyage_id !== null,
    needsRecalc: raw.needs_recalc === true,
  }
}

const CALCULATION_PAGE_SIZE = 20

/** 한 페이지 — 최신순(`API_SPEC §1.9`). 응답 모양이 어긋나면 던진다(빈 목록으로 삼키지 않는다). */
export async function fetchCalculationPage(
  vesselId: string,
  cursor: string | null,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<CalculationPage> {
  const params = new URLSearchParams({ vessel_id: vesselId, limit: String(CALCULATION_PAGE_SIZE) })
  if (cursor) params.set('cursor', cursor)
  const response = await fetchImpl(`${baseUrl}/calculations?${params.toString()}`, {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  if (response.status === 401) {
    redirectToLogin()
    throw new Error(SESSION_EXPIRED_MESSAGE)
  }
  if (!response.ok) throw new Error(`계산 이력을 불러오지 못했습니다 (HTTP ${response.status}).`)
  const body = (await response.json()) as {
    data?: unknown
    meta?: { next_cursor?: string | null; has_more?: boolean }
  }
  if (!Array.isArray(body.data)) throw new Error('계산 이력 응답 형식이 올바르지 않습니다.')
  return {
    rows: (body.data as ServerRun[]).map(toCalculationRow),
    nextCursor: body.meta?.next_cursor ?? null,
    hasMore: body.meta?.has_more === true,
  }
}
