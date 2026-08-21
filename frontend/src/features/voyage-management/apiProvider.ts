import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { createApiParametersProvider } from '../parameters/apiProvider'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import { actualsPayload, policyForTransition } from './voyageRules'
import type {
  ActualsDraft,
  InclusionPolicy,
  ManagedVoyage,
  VoyageDraft,
  VoyageFuelUse,
  VoyageStatus,
} from './types'

/**
 * 항차 관리 provider — `API_SPEC §3.1`·`§3.3`·`§3.5`·`§3.6` (`#610`).
 *
 * 구성은 `not-underway/apiProvider.ts`와 같다 — 같은 `fetch`·`baseUrl`을 연료
 * 선택지 provider에도 넘겨, 테스트가 하나만 갈아 끼워도 둘 다 대체된다.
 *
 * ## 서버 오류 문구를 그대로 쓴다
 *
 * 422는 어느 항목이 문제인지 `details[].field`에 실려 온다. 화면이 다시 쓰면
 * **전환 가드가 왜 막혔는지**(실적 누락·기준연도 없음)를 잃는다.
 *
 * ## 숫자를 문자열로 두지 않는다
 *
 * 계획값·실적값은 사용자가 넣은 입력이지 Layer 1 계산 결과가 아니다.
 * `API_SPEC §1.7`의 문자열 직렬화는 계산 결과에만 적용된다.
 */

export class VoyageError extends Error {
  /** 422 `details[].field` — 화면이 해당 입력창 아래에 붙인다. */
  readonly field?: string

  constructor(message: string, options?: { field?: string; cause?: unknown }) {
    super(message, { cause: options?.cause })
    this.name = 'VoyageError'
    this.field = options?.field
  }
}

interface ServerFuelUse {
  fuel_type?: unknown
  planned_fuel_ton?: unknown
  actual_fuel_ton?: unknown
}

interface ServerVoyage {
  id?: unknown
  voyage_no?: unknown
  status?: unknown
  annual_inclusion_policy?: unknown
  regulation_year?: unknown
  departure_port_name?: unknown
  arrival_port_name?: unknown
  planned_distance_nm?: unknown
  planned_speed_kn?: unknown
  actual_distance_nm?: unknown
  actual_avg_speed_kn?: unknown
  fuel_uses?: unknown
}

interface ServerError {
  error?: {
    message?: string
    details?: Array<{ field?: string; message?: string }>
  }
}

/** 숫자로 읽되, 없거나 숫자가 아니면 `null`이다. 0을 `null`로 만들지 않는다. */
function num(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim() !== '') {
    const value = Number(raw)
    return Number.isFinite(value) ? value : null
  }
  return null
}

function text(raw: unknown): string | null {
  return typeof raw === 'string' && raw !== '' ? raw : null
}

function toFuelUse(raw: ServerFuelUse): VoyageFuelUse {
  return {
    fuelType: String(raw.fuel_type ?? ''),
    plannedFuelTon: num(raw.planned_fuel_ton),
    actualFuelTon: num(raw.actual_fuel_ton),
  }
}

function toVoyage(raw: ServerVoyage): ManagedVoyage {
  return {
    id: String(raw.id ?? ''),
    voyageNo: text(raw.voyage_no),
    status: (raw.status ?? 'DRAFT') as VoyageStatus,
    inclusionPolicy: (raw.annual_inclusion_policy ?? 'EXCLUDE') as InclusionPolicy,
    regulationYear: num(raw.regulation_year),
    departurePortName: text(raw.departure_port_name),
    arrivalPortName: text(raw.arrival_port_name),
    plannedDistanceNm: num(raw.planned_distance_nm),
    plannedSpeedKn: num(raw.planned_speed_kn),
    actualDistanceNm: num(raw.actual_distance_nm),
    actualAvgSpeedKn: num(raw.actual_avg_speed_kn),
    fuelUses: Array.isArray(raw.fuel_uses) ? (raw.fuel_uses as ServerFuelUse[]).map(toFuelUse) : [],
  }
}

export interface VoyageManagementProvider {
  list(vesselId: string): Promise<{ voyages: ManagedVoyage[]; fuelTypes: string[] }>
  create(vesselId: string, draft: VoyageDraft): Promise<ManagedVoyage>
  transition(voyage: ManagedVoyage, to: VoyageStatus): Promise<ManagedVoyage>
  saveActuals(voyageId: string, draft: ActualsDraft): Promise<ManagedVoyage>
}

export function createApiVoyageManagementProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): VoyageManagementProvider {
  const parameters = createApiParametersProvider(fetchImpl, baseUrl)

  const call = async (
    path: string,
    init: RequestInit = {},
  ): Promise<Record<string, unknown> | null> => {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        credentials: 'include',
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init.body ? { 'Content-Type': 'application/json' } : {}),
          ...csrfHeaders(),
          ...init.headers,
        },
      })
    } catch (cause) {
      throw new VoyageError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new VoyageError('세션이 만료되었습니다.')
    }

    const body = (await response.json().catch(() => null)) as
      | (Record<string, unknown> & ServerError)
      | null

    if (!response.ok) {
      const detail = body?.error?.details?.[0]
      throw new VoyageError(
        body?.error?.message ?? `요청에 실패했습니다 (HTTP ${response.status}).`,
        { field: detail?.field },
      )
    }
    return body
  }

  const readVoyage = (body: Record<string, unknown> | null): ManagedVoyage => {
    const data = body?.data as ServerVoyage | undefined
    if (!data) throw new VoyageError('응답 형식이 올바르지 않습니다.')
    return toVoyage(data)
  }

  return {
    async list(vesselId) {
      /*
       * 연료 선택지는 `/parameters/fuel-types`에서 온다 (`#444`). 항차 목록과
       * 서로 의존이 없어 **병렬로** 보낸다.
       */
      const [body, fuelTypes] = await Promise.all([
        call(`/vessels/${vesselId}/voyages?limit=100`),
        parameters.listFuelTypes(),
      ])
      return {
        voyages: ((body?.data ?? []) as ServerVoyage[]).map(toVoyage),
        fuelTypes: fuelTypes.map((fuel) => fuel.code),
      }
    },

    async create(vesselId, draft) {
      const year = draft.regulationYear.trim()
      const body = await call(`/vessels/${vesselId}/voyages`, {
        method: 'POST',
        body: JSON.stringify({
          voyage_no: draft.voyageNo.trim(),
          departure_port_name: draft.departurePortName.trim(),
          arrival_port_name: draft.arrivalPortName.trim(),
          planned_distance_nm: Number(draft.plannedDistanceNm),
          planned_speed_kn: Number(draft.plannedSpeedKn),
          // optional — `INCLUDE_AS_PLAN` 전환 시점에만 필수(`§3.3` [#150]).
          ...(year === '' ? {} : { regulation_year: Number(year) }),
          fuel_uses: [
            {
              fuel_type: draft.fuelType,
              planned_fuel_ton: Number(draft.plannedFuelTon),
              source: 'USER_INPUT',
            },
          ],
          /*
           * `annual_inclusion_policy`를 보내지 않는다 — `§3.3` [EXT-P0-4].
           * 생성 결과는 항상 `DRAFT` · `EXCLUDE`이고, 그것은 서버가 정한다.
           */
        }),
      })
      return readVoyage(body)
    },

    async transition(voyage, to) {
      /*
       * **policy를 언제 실을지는 규칙 모듈이 정한다.**
       *
       * 생략하면 현행 유지인데, 목표 상태가 현행을 허용하지 않으면 서버가 자동
       * 보정하지 않고 422로 거부한다(`§3.5`). `INCLUDE_AS_PLAN` 항차를 완료로
       * 옮기는 데모 마지막 걸음이 정확히 그 경우다.
       */
      const policy = policyForTransition(voyage.inclusionPolicy, to)
      const body = await call(`/voyages/${voyage.id}/transition`, {
        method: 'POST',
        body: JSON.stringify({
          to_status: to,
          ...(policy === null ? {} : { annual_inclusion_policy: policy }),
        }),
      })
      return readVoyage(body)
    },

    async saveActuals(voyageId, draft) {
      /*
       * 본문은 `actualsPayload`가 만든다 — 빈 칸은 키 자체를 넣지 않는다.
       * 생략이 「변경 없음」이므로 `null`을 보내면 지우라는 뜻이 되어 버린다.
       *
       * 계획값은 실리지 않는다. 요청 본문에 `planned_*`가 없는 것이 계약이고
       * (`§3.6`), 계획 대비 실적 차이가 `#363` 피드백 루프의 입력이다.
       */
      const body = await call(`/voyages/${voyageId}/actuals`, {
        method: 'PUT',
        body: JSON.stringify(actualsPayload(draft)),
      })
      return readVoyage(body)
    },
  }
}
