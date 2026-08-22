import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { readPageMeta } from '../vessel-management/apiProvider'
import { createApiParametersProvider } from '../parameters/apiProvider'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type { ImportResult, ImportRowError } from './importRules'
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

/**
 * 항차 목록 응답의 한 행 (`GET /vessels/{id}/voyages`).
 *
 * ## 공용화하지 않는다 — 세 벌은 같은 타입이 아니다 (`#627` 판정)
 *
 * 같은 이름이 세 곳에 있다. `#610`이 「공용화 여부를 먼저 판단한다」를 남겼고,
 * 여기서 판단한다.
 *
 * | 파일 | 출처 | 형 |
 * |---|---|---|
 * | `realtime-cii/apiProvider.ts` | **`GET /cii/current`의 `current_voyage`** | 확정 |
 * | `reports/apiProvider.ts` | `GET /vessels/{id}/voyages` (**부분집합** 6필드) | 확정 |
 * | 이 파일 | `GET /vessels/{id}/voyages` (전 필드) | **`unknown`** |
 *
 * `realtime-cii` 쪽은 **다른 엔드포인트**다 — 키가 `id`가 아니라 `voyage_id`이고
 * `underway_hours`·`is_simulated`·`attained_cii`를 단다. 이름만 같다.
 *
 * 나머지 둘은 같은 엔드포인트지만 **안전성 전략이 반대**다. 합치면 한쪽이 자기 것을
 * 잃는다 — `reports`를 `unknown`으로 바꾸면 파싱 코드가 늘고, 이 파일을 확정 타입으로
 * 바꾸면 **서버가 형을 바꿔도 컴파일이 통과한다.**
 *
 * 진짜 해법은 서버가 응답 스키마를 강제하는 것이고(`#559`), 그 전에 프론트에서 타입만
 * 합치면 **강제 없는 공유 타입**이 된다 — 어긋나도 아무도 모른다.
 */
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
  /**
   * 항차 한 페이지 (`API_SPEC §3.1` 커서 페이지네이션).
   *
   * **`cursor`를 받는 이유** — 종전에는 `?limit=100`만 박고 `meta.next_cursor`를
   * 버렸다. `#625`가 한 번에 1,000행을 넣을 수 있게 만든 뒤, **101번째부터는 화면에서
   * 도달할 방법이 없었다.**
   *
   * `fuelTypes`는 첫 페이지에서만 의미가 있으나 매번 함께 돌려준다 — 호출부가
   * 「이번이 첫 페이지인가」를 따지지 않아도 되게 한다.
   */
  list(
    vesselId: string,
    cursor?: string | null,
  ): Promise<{
    voyages: ManagedVoyage[]
    fuelTypes: string[]
    nextCursor: string | null
    hasMore: boolean
  }>
  create(vesselId: string, draft: VoyageDraft): Promise<ManagedVoyage>
  transition(voyage: ManagedVoyage, to: VoyageStatus): Promise<ManagedVoyage>
  saveActuals(voyageId: string, draft: ActualsDraft): Promise<ManagedVoyage>
  /**
   * CSV 가져오기 (`API_SPEC §8.2`).
   *
   * `dryRun`이면 **검증만 하고 아무것도 저장하지 않는다.** 화면은 이 걸음을 먼저
   * 밟고 결과를 보인 뒤에야 확정한다 — 부분 성공 계약이라 확인 없이 올리면
   * 되돌릴 수 없는 상태가 만들어진다.
   */
  importCsv(vesselId: string, file: File, options: { dryRun: boolean }): Promise<ImportResult>
}

interface ServerImportError {
  row?: unknown
  field?: unknown
  message?: unknown
}

interface ServerImportResult {
  imported_count?: unknown
  skipped_count?: unknown
  errors?: unknown
  dry_run?: unknown
}

function toImportError(raw: ServerImportError): ImportRowError {
  return {
    row: typeof raw.row === 'number' ? raw.row : 0,
    field: typeof raw.field === 'string' ? raw.field : 'file',
    message: typeof raw.message === 'string' ? raw.message : '알 수 없는 오류입니다.',
  }
}

function toImportResult(raw: ServerImportResult): ImportResult {
  return {
    importedCount: typeof raw.imported_count === 'number' ? raw.imported_count : 0,
    skippedCount: typeof raw.skipped_count === 'number' ? raw.skipped_count : 0,
    errors: Array.isArray(raw.errors) ? raw.errors.map(toImportError) : [],
    /*
     * **`dry_run`을 응답에서 읽는다.** 요청에 무엇을 보냈는지로 판단하지 않는다 —
     * 두 값이 갈리면 저장된 것을 「아직 저장 안 됨」으로 보이게 되고, 그 화면에서
     * 사용자는 같은 파일을 한 번 더 올린다.
     */
    dryRun: raw.dry_run === true,
  }
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
    async list(vesselId, cursor = null) {
      /*
       * 연료 선택지는 `/parameters/fuel-types`에서 온다 (`#444`). 항차 목록과
       * 서로 의존이 없어 **병렬로** 보낸다.
       *
       * `limit`은 서버 상한(`MAX_LIMIT = 100`, `repositories/voyage.py:23`)에 맞춘다 —
       * 더 크게 보내도 서버가 잘라 요청 수만 늘어난다.
       */
      const query = `limit=100${cursor === null ? '' : `&cursor=${encodeURIComponent(cursor)}`}`
      const [body, fuelTypes] = await Promise.all([
        call(`/vessels/${vesselId}/voyages?${query}`),
        parameters.listFuelTypes(),
      ])
      const page = readPageMeta(body)
      return {
        voyages: ((body?.data ?? []) as ServerVoyage[]).map(toVoyage),
        fuelTypes: fuelTypes.map((fuel) => fuel.code),
        nextCursor: page.nextCursor,
        hasMore: page.hasMore,
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
          /*
           * 연료를 **여러 줄로** 보낸다 (`#636`). 종전에는 폼이 단일 값이라 배열에
           * 한 줄만 담았고, 화면으로 만든 항차는 연료가 반드시 한 종이었다.
           *
           * `source: 'USER_INPUT'`은 그대로다 — 사용자가 직접 넣은 값이다
           * (`DB_SCHEMA §2.3` · 리포트 표기는 `#645`).
           */
          fuel_uses: draft.fuelUses.map((fu) => ({
            fuel_type: fu.fuelType,
            planned_fuel_ton: Number(fu.plannedFuelTon),
            source: 'USER_INPUT',
          })),
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

    async importCsv(vesselId, file, options) {
      /*
       * `Content-Type`을 직접 넣지 않는다 — `FormData`를 주면 브라우저가 multipart
       * 경계 문자열을 포함해 붙인다. 손으로 적으면 경계가 빠져 서버가 파싱에 실패한다.
       *
       * `call()`은 `init.body`가 있으면 JSON 헤더를 붙이므로 이 경로에서는 쓰지 않는다.
       */
      const form = new FormData()
      form.append('file', file)
      // `§8.2` 표의 유일한 값이지만 **생략하지 않는다.** 서버가 기본값을 바꾸면
      // 화면이 의도한 것과 다른 자료가 들어간다.
      form.append('type', 'voyages')

      let response: Response
      try {
        response = await fetchImpl(
          `${baseUrl}/vessels/${vesselId}/import?dry_run=${options.dryRun}`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { Accept: 'application/json', ...csrfHeaders() },
            body: form,
          },
        )
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
        /*
         * 파일 단위 거부(크기·형식·인코딩·필수 컬럼)는 여기로 온다 — `errors[]`가
         * 아니라 422다. **한 행도 읽지 않은 상태**이므로 행 오류와 다르게 보인다.
         */
        const detail = body?.error?.details?.[0]
        throw new VoyageError(
          body?.error?.message ?? `가져오지 못했습니다 (HTTP ${response.status}).`,
          { field: detail?.field },
        )
      }

      const data = (body?.data ?? null) as ServerImportResult | null
      if (!data) throw new VoyageError('응답 형식이 올바르지 않습니다.')
      return toImportResult(data)
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
