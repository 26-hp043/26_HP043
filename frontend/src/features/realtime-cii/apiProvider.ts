import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type {
  CapacityBasis,
  RealtimeCii,
  RealtimeCiiProvider,
  Rating,
  RatingBoundaries,
  Substitution,
  VoyageSegment,
  YearEndProjection,
  YtdValues,
} from './types'

/**
 * 실시간 CII provider — `GET /vessels/{id}/cii/current` (`API_SPEC §2.14` · `#357`).
 *
 * ## 호출이 하나다
 *
 * 이슈는 *"두 엔드포인트를 호출하므로 `as_of`가 어긋나면 재조회"* 를 요구했다.
 * `#354`가 **3종 값을 한 응답에 담도록** 설계돼 그 상황이 생기지 않는다 — 재조회
 * 로직을 넣는 대신 어긋날 수 없게 만든 쪽이다. 값이 늘어 호출이 갈라지는 날
 * `as_of` 비교가 필요해지므로, 이 파일이 `asOf`를 화면까지 올려 둔다.
 *
 * ## 수치를 되돌리지 않는다
 *
 * 응답 문자열을 그대로 넘긴다(`API_SPEC §1.7`).
 */

export class RealtimeCiiError extends Error {
  /** 404 — 없는 선박. 화면이 「불러오기 실패」와 다르게 표시한다. */
  readonly notFound: boolean

  constructor(message: string, options?: { notFound?: boolean; cause?: unknown }) {
    super(message, { cause: options?.cause })
    this.name = 'RealtimeCiiError'
    this.notFound = options?.notFound ?? false
  }
}

interface ServerYtd {
  data_available: boolean
  attained_cii: string | null
  required_cii: string | null
  ratio_to_required: string | null
  rating: string | null
  risk_level: string | null
  margin_ratio: string | null
  boundaries?: ServerBoundaries | null
  total_co2_ton: string | null
  total_fuel_ton: string | null
  underway_distance_nm: string | null
  not_underway_distance_nm: string | null
  total_distance_nm: string | null
  voyage_count: number
  not_underway_period_count: number
  substitutions?: ServerSubstitution[]
}

/**
 * 서버의 등급 경계 (`#725`).
 *
 * 키에 `_boundary`가 붙는다 — `rating_engine`의 `superior_boundary` 등을 그대로
 * 내보낸 것이다. 화면 타입에서 접미사를 떼는 것은 **여기 한 곳에서만** 한다.
 */
interface ServerBoundaries {
  superior_boundary?: unknown
  lower_boundary?: unknown
  upper_boundary?: unknown
  inferior_boundary?: unknown
}

interface ServerSubstitution {
  voyage_id?: unknown
  axis?: unknown
  fuel_type?: unknown
}

/**
 * **`GET /vessels/{id}/cii/current`의 `current_voyage`**다 — 항차 목록 응답이 아니다.
 *
 * 이름이 `voyage-management`·`reports`의 `ServerVoyage`와 같지만 **다른 엔드포인트**이며,
 * 키부터 다르다(`voyage_id` vs `id`). 실시간 계산 결과(`underway_hours`·`is_simulated`·
 * `attained_cii`)를 달고 있어 합칠 수 있는 타입이 아니다.
 *
 * 공용화 판단은 `voyage-management/apiProvider.ts`에 남겼다 (`#627`).
 */
interface ServerVoyage {
  voyage_id: string
  voyage_no: string | null
  status: string
  departure_port_name: string | null
  arrival_port_name: string | null
  planned_distance_nm: string | null
  underway_hours: string | null
  distance_nm: string | null
  fuel_ton: string | null
  fuel_type: string | null
  is_simulated: boolean
  attained_cii: string | null
  co2_ton: string | null
}

interface ServerProjection {
  data_available: boolean
  reason: string | null
  attained_cii?: string | null
  required_cii?: string | null
  ratio_to_required?: string | null
  rating?: string | null
  risk_level?: string | null
  assumptions?: Record<string, string | null>
}

interface ServerData {
  vessel_id: string
  vessel_name: string
  regulation_year: number
  transport_capacity_basis: string
  underway_state: string | null
  ytd: ServerYtd
  current_voyage: ServerVoyage | null
  year_end_projection: ServerProjection
  warnings: string[]
}

function toYtd(raw: ServerYtd): YtdValues {
  return {
    dataAvailable: raw.data_available,
    attainedCii: raw.attained_cii,
    requiredCii: raw.required_cii,
    ratioToRequired: raw.ratio_to_required,
    rating: raw.rating as Rating | null,
    riskLevel: raw.risk_level,
    marginRatio: raw.margin_ratio,
    boundaries: toBoundaries(raw.boundaries),
    totalCo2Ton: raw.total_co2_ton,
    totalFuelTon: raw.total_fuel_ton,
    underwayDistanceNm: raw.underway_distance_nm,
    notUnderwayDistanceNm: raw.not_underway_distance_nm,
    totalDistanceNm: raw.total_distance_nm,
    voyageCount: raw.voyage_count,
    notUnderwayPeriodCount: raw.not_underway_period_count,
    /*
     * **없으면 빈 배열로 읽는다.** 서버가 이 필드를 싣기 시작한 것은 `#449`이고,
     * 그 전 응답이나 다른 갈래에서는 키 자체가 없을 수 있다. `undefined`가
     * 흘러가면 화면이 「대체 없음」과 「모름」을 구분하지 못한 채 터진다.
     */
    substitutions: (raw.substitutions ?? []).map(toSubstitution),
  }
}

/**
 * 경계 넷 — **하나라도 없으면 `null`** (`#725`).
 *
 * `data_available`가 거짓이면 서버가 `boundaries` 자체를 `null`로 싣고, 개별 값이
 * 빠지는 경우도 형태상 가능하다. 부분값을 그대로 올리면 스케일 바가 **구간 셋만
 * 있는 축**을 그리려다 조용히 어긋난다 — 못 그리는 것은 여기서 확정한다.
 */
function toBoundaries(raw: ServerBoundaries | null | undefined): RatingBoundaries | null {
  if (!raw) return null
  const superior = raw.superior_boundary
  const lower = raw.lower_boundary
  const upper = raw.upper_boundary
  const inferior = raw.inferior_boundary
  if (
    typeof superior !== 'string' ||
    typeof lower !== 'string' ||
    typeof upper !== 'string' ||
    typeof inferior !== 'string'
  ) {
    return null
  }
  return { superior, lower, upper, inferior }
}

function toSubstitution(raw: ServerSubstitution): Substitution {
  return {
    voyageId: String(raw.voyage_id ?? ''),
    axis: raw.axis === 'DISTANCE' ? 'DISTANCE' : 'FUEL',
    fuelType: typeof raw.fuel_type === 'string' ? raw.fuel_type : null,
  }
}

function toVoyage(raw: ServerVoyage): VoyageSegment {
  return {
    voyageId: raw.voyage_id,
    voyageNo: raw.voyage_no,
    status: raw.status,
    departurePortName: raw.departure_port_name,
    arrivalPortName: raw.arrival_port_name,
    plannedDistanceNm: raw.planned_distance_nm,
    underwayHours: raw.underway_hours,
    distanceNm: raw.distance_nm,
    fuelTon: raw.fuel_ton,
    fuelType: raw.fuel_type,
    isSimulated: raw.is_simulated,
    attainedCii: raw.attained_cii,
    co2Ton: raw.co2_ton,
    /*
     * 서버가 준 값을 읽지 않고 `null`로 고정한다. `COR-1`이 항차 구간값에 등급을
     * 금지하므로, 서버가 실수로 등급을 실어 보내도 화면에는 오지 않아야 한다.
     */
    rating: null,
  }
}

function toProjection(raw: ServerProjection): YearEndProjection {
  const a = raw.assumptions
  return {
    dataAvailable: raw.data_available,
    reason: raw.reason ?? null,
    attainedCii: raw.attained_cii ?? null,
    requiredCii: raw.required_cii ?? null,
    ratioToRequired: raw.ratio_to_required ?? null,
    rating: (raw.rating ?? null) as Rating | null,
    riskLevel: raw.risk_level ?? null,
    assumptions: a
      ? {
          method: a.method ?? '',
          elapsedDays: a.elapsed_days ?? null,
          remainingDays: a.remaining_days ?? null,
          dailyDistanceNm: a.daily_distance_nm ?? null,
          dailyFuelTon: a.daily_fuel_ton ?? null,
          projectedExtraDistanceNm: a.projected_extra_distance_nm ?? null,
          projectedExtraFuelTon: a.projected_extra_fuel_ton ?? null,
          fuelType: a.fuel_type ?? null,
        }
      : null,
  }
}

export function createApiRealtimeCiiProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): RealtimeCiiProvider {
  return {
    async load(vesselId: string): Promise<RealtimeCii> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/vessels/${vesselId}/cii/current`, {
          method: 'GET',
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
        })
      } catch (cause) {
        throw new RealtimeCiiError('서버에 연결하지 못했습니다.', { cause })
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new RealtimeCiiError('세션이 만료되었습니다.')
      }
      if (response.status === 404) {
        throw new RealtimeCiiError('선박을 찾을 수 없습니다.', { notFound: true })
      }

      const body = (await response.json().catch(() => null)) as {
        data?: ServerData
        meta?: { as_of?: string; simulated?: boolean }
        error?: { message?: string }
      } | null

      if (!response.ok) {
        throw new RealtimeCiiError(
          body?.error?.message ?? `불러오지 못했습니다 (HTTP ${response.status}).`,
        )
      }

      const data = body?.data
      if (!data) throw new RealtimeCiiError('응답 형식이 올바르지 않습니다.')

      /*
       * 축이 없으면 단위를 만들 수 없다. `DESIGN_SYSTEM §4.1` 🔒가 고정 문자열을
       * 금지하므로 임의로 `DWT`를 채우지 않는다 — 크루즈선에 `DWT`가 표시되면
       * 화면은 깨지지 않고 내용만 틀린다.
       */
      const basis = data.transport_capacity_basis
      if (basis !== 'DWT' && basis !== 'GT') {
        throw new RealtimeCiiError('표시 단위의 축을 확인할 수 없습니다.')
      }

      const asOf = body?.meta?.as_of
      if (!asOf) {
        /*
         * `as_of`가 없으면 화면이 「언제 기준 값인지」를 말할 수 없다. 실시간
         * 화면에서 그건 값 자체보다 중요한 정보다 — 없으면 오류로 만든다.
         */
        throw new RealtimeCiiError('기준 시각을 확인할 수 없습니다.')
      }

      return {
        vesselId: data.vessel_id,
        vesselName: data.vessel_name,
        regulationYear: data.regulation_year,
        capacityBasis: basis as CapacityBasis,
        underwayState:
          data.underway_state === 'UNDER_WAY' || data.underway_state === 'NOT_UNDER_WAY'
            ? data.underway_state
            : null,
        ytd: toYtd(data.ytd),
        currentVoyage: data.current_voyage ? toVoyage(data.current_voyage) : null,
        projection: toProjection(data.year_end_projection),
        warnings: data.warnings ?? [],
        asOf,
        /*
         * 배지 판정은 **서버 값 그대로**다. 화면이 조건을 덧붙이면 `PRD R-5`의
         * 표기 의무가 화면 구현에 좌우된다. 값이 없으면 참으로 둔다 — 배지를
         * 잘못 띄우는 쪽이 잘못 감추는 쪽보다 안전하다.
         */
        simulated: body?.meta?.simulated ?? true,
      }
    },
  }
}
