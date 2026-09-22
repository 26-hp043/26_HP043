import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../../api/base'
import { ParametersError } from '../../api/parameters'

/**
 * 규제 기준값 **표 조회** — `API_SPEC §7.1~§7.4` 네 표를 행 그대로 받는다 (`#1516` · 서버 보강은 `#1515`).
 *
 * ## `apiProvider.ts`와 따로 두는 이유
 *
 * 그쪽 `ParametersProvider`는 **선택지**를 위한 것이다 — `listRegulationYears()`가 연도
 * 숫자만 돌려주는 것도 *「Z계수를 들고 오면 화면이 계산에 쓸 수 있는 상태가 된다」*는
 * 판단이다. 이 모듈은 반대로 **값을 대조하는 자리**(설정의 「규제 기준값」 절)를 위한
 * 것이라 행을 통째로 받는다. 같은 인터페이스에 섞으면 선택지 소비처가 계산 재료까지
 * 손에 쥐게 된다.
 *
 * ## 값을 가공하지 않는다 (`#1239` 결정 G)
 *
 * 숫자 필드(`z_factor_percent` · `a_decimal` · `c` · `d1`~`d4` · `cf`)는 서버가
 * **문자열**로 준다(`API_SPEC §1.7`). 이 절은 규제 상수를 원문과 대조하는 자리이므로
 * `Number`로 되돌리지도, 자릿수를 맞추지도 않는다 — 표시도 문자열 그대로다.
 *
 * ## 서버 계약에서 선택적으로 받는 것
 *
 * `version` · `is_active`는 기준선·등급 경계 응답에 `#1515`가 더하는 필드다. 그 PR이
 * 먼저 머지되지 않은 서버에서도 화면이 깨지지 않도록 **없으면 활성으로 본다** — 기본 조회가
 * 활성만 돌려주는 계약이라(`API_SPEC §7.5` 「개정의 반영 방식」) 그 해석이 맞다.
 * `?active=`를 아직 모르는 서버는 그 인자를 무시하고 활성분을 주므로, 「이전 판본 포함」을
 * 켰는데 이행 행이 없는 상태로 그려진다 — 틀린 값이 보이는 것은 아니다.
 */

export interface ReferenceListOptions {
  /** `true`면 `?active=false`로 이행 행(대체된 옛 판본)까지 받는다. 기본은 활성만. */
  includeInactive?: boolean
}

/** `API_SPEC §7.1` 규정 연도 1행. */
export interface RegulationYearRow {
  year: number
  /** **문자열이다** — 서버 표기 그대로 (`API_SPEC §1.7`). */
  zFactorPercent: string
  effectiveFrom: string
  sourceRef: string
  version: string
  isActive: boolean
}

/** `API_SPEC §7.3` 선종별 기준선 1행. */
export interface ReferenceLineRow {
  shipType: string
  conditionExpr: string
  capacityRule: string
  /** IMO 원문 표기(`14479E10` 같은 과학 표기). 대조의 기준은 이쪽이다. */
  aRaw: string
  /** `a_raw`를 서버가 풀어 쓴 십진 문자열 — 보조 표기. */
  aDecimal: string
  c: string
  sourceRef: string
  /** `#1515`가 더하는 필드. 없는 서버에서는 `null`. */
  version: string | null
  isActive: boolean
}

/** `API_SPEC §7.4` 등급 경계 1행. */
export interface RatingBoundaryRow {
  shipType: string
  conditionExpr: string
  capacityBasis: string
  d1: string
  d2: string
  d3: string
  d4: string
  sourceRef: string
  version: string | null
  isActive: boolean
}

/** `API_SPEC §7.2` 연료 종류 1행 — 이력이 없다(제자리 갱신). */
export interface FuelTypeRow {
  code: string
  displayName: string
  cf: string
  unit: string
  sourceRef: string
  isActive: boolean
}

export interface ReferenceParametersProvider {
  listRegulationYears(options?: ReferenceListOptions): Promise<RegulationYearRow[]>
  listReferenceLines(options?: ReferenceListOptions): Promise<ReferenceLineRow[]>
  listRatingBoundaries(options?: ReferenceListOptions): Promise<RatingBoundaryRow[]>
  /**
   * 연료는 `includeInactive`를 받지 않는다. 지금 서버의 `?active=false`는 「비활성만」이고
   * (`repositories/parameters.py` `list_fuel_types` — 세 값), 이력이 없는 표에 그 갈래를
   * 열어 둘 이유가 없다.
   */
  listFuelTypes(): Promise<FuelTypeRow[]>
}

type RawRow = Record<string, unknown>

/** 문자열 필드. 서버가 숫자로 주는 경우(`year`처럼)는 JSON 리터럴 그대로 잇는다. */
function text(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

/** 기본 조회는 활성만 돌려주므로(`API_SPEC §7`), 필드가 없으면 활성으로 본다. */
function active(value: unknown): boolean {
  return value !== false
}

function optionalText(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

export function createApiReferenceParametersProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): ReferenceParametersProvider {
  /**
   * 한 표를 받는다. 오류 처리는 `apiProvider.ts`와 같은 관례 — 네트워크 실패는 문구로
   * 옮기고, 401은 로그인으로 보내며, 본문이 배열이 아니면 **던지지 않고 빈 목록**이다
   * (이 절이 못 떠도 설정 화면의 계정 절은 떠야 한다).
   */
  async function rows(path: string, label: string): Promise<RawRow[]> {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        credentials: 'include',
        headers: { Accept: 'application/json', ...csrfHeaders() },
      })
    } catch (cause) {
      throw new ParametersError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new ParametersError(SESSION_EXPIRED_MESSAGE)
    }

    const body = (await response.json().catch(() => null)) as
      | { data?: unknown; error?: { message?: unknown } }
      | null

    if (!response.ok) {
      const serverMessage = body?.error?.message
      throw new ParametersError(
        typeof serverMessage === 'string' && serverMessage !== ''
          ? serverMessage
          : `${label}을 불러오지 못했습니다 (HTTP ${response.status}).`,
      )
    }

    return Array.isArray(body?.data) ? (body.data as RawRow[]) : []
  }

  /** 세 표의 `?active=` — 명시적으로 보낸다. 모르는 서버는 무시하고 활성분을 준다. */
  function activeQuery(options?: ReferenceListOptions): string {
    return options?.includeInactive ? '?active=false' : '?active=true'
  }

  return {
    async listRegulationYears(options) {
      const raw = await rows(`/parameters/regulation-years${activeQuery(options)}`, '규정 연도 목록')
      return raw
        .filter((row) => typeof row.year === 'number' && Number.isInteger(row.year))
        .map((row) => ({
          year: row.year as number,
          zFactorPercent: text(row.z_factor_percent),
          effectiveFrom: text(row.effective_from),
          sourceRef: text(row.source_ref),
          version: text(row.version),
          isActive: active(row.is_active),
        }))
    },

    async listReferenceLines(options) {
      const raw = await rows(`/parameters/reference-lines${activeQuery(options)}`, '선종별 기준선')
      return raw
        .filter((row) => typeof row.ship_type === 'string')
        .map((row) => ({
          shipType: row.ship_type as string,
          conditionExpr: text(row.condition_expr),
          capacityRule: text(row.capacity_rule),
          aRaw: text(row.a_raw),
          aDecimal: text(row.a_decimal),
          c: text(row.c),
          sourceRef: text(row.source_ref),
          version: optionalText(row.version),
          isActive: active(row.is_active),
        }))
    },

    async listRatingBoundaries(options) {
      const raw = await rows(`/parameters/rating-boundaries${activeQuery(options)}`, '등급 경계')
      return raw
        .filter((row) => typeof row.ship_type === 'string')
        .map((row) => ({
          shipType: row.ship_type as string,
          conditionExpr: text(row.condition_expr),
          capacityBasis: text(row.capacity_basis),
          d1: text(row.d1),
          d2: text(row.d2),
          d3: text(row.d3),
          d4: text(row.d4),
          sourceRef: text(row.source_ref),
          version: optionalText(row.version),
          isActive: active(row.is_active),
        }))
    },

    async listFuelTypes() {
      const raw = await rows('/parameters/fuel-types', '연료 탄소계수')
      return raw
        .filter((row) => typeof row.code === 'string')
        .map((row) => ({
          code: row.code as string,
          displayName: typeof row.display_name === 'string' ? row.display_name : (row.code as string),
          cf: text(row.cf),
          unit: text(row.unit),
          sourceRef: text(row.source_ref),
          isActive: active(row.is_active),
        }))
    },
  }
}
