import { csrfHeaders, redirectToLogin } from '../auth/session'
import { DEFAULT_API_BASE_URL } from '../features/voyage-cii/apiProvider'
import {
  API_BASE_URL_ENV_KEY,
  shouldUseApi,
} from '../features/voyage-cii/providerSelection'

/**
 * 항차 선택지의 데이터 경계 (#512).
 *
 * `vesselCatalog.ts`(#236)와 같은 구성이다 — 화면은 출처를 알지 않고, demo ↔ 실 API
 * 전환은 **같은 환경변수**(`VITE_USE_API`)로 결정된다.
 *
 * ## demo에는 항차 목록이 없다
 *
 * 고정표(`referenceTable.ts`)는 계산 입력을 담고 있을 뿐 항차를 갖지 않는다.
 * 지어내지 않고 **빈 목록**을 돌려준다 — 상단바가 「항차 없음」으로 표시하며,
 * 그것이 사실이다.
 */

/** 상단바 셀렉트가 쓰는 최소 형태. */
export interface VoyageOption {
  id: string
  /** 항차 번호. 없으면 출발항 → 도착항으로 대신한다. */
  displayName: string
  status: string
}

export interface VoyageCatalogProvider {
  listVoyages(vesselId: string): Promise<VoyageOption[]>
}

/** demo 구현 — 항차가 없다. */
export function createDemoVoyageCatalog(): VoyageCatalogProvider {
  return {
    async listVoyages() {
      return []
    },
  }
}

/** `GET /vessels/{id}/voyages` 응답 중 선택지에 필요한 부분 (`API_SPEC §3.1`). */
interface VoyageListItem {
  id?: unknown
  voyage_no?: unknown
  status?: unknown
  departure_port_name?: unknown
  arrival_port_name?: unknown
}

/**
 * 표시 이름을 만든다.
 *
 * `voyage_no`가 있으면 그것이 사람이 부르는 이름이다. 없으면 구간으로 대신하고,
 * 그것도 없으면 **id 앞자리**를 보인다 — 「이름 없는 항차」로 뭉뚱그리면 여러 건이
 * 같은 문자열이 되어 고를 수 없다.
 */
export function voyageDisplayName(row: VoyageListItem): string {
  if (typeof row.voyage_no === 'string' && row.voyage_no.trim() !== '') return row.voyage_no
  const from = typeof row.departure_port_name === 'string' ? row.departure_port_name : ''
  const to = typeof row.arrival_port_name === 'string' ? row.arrival_port_name : ''
  if (from !== '' || to !== '') return `${from || '—'} → ${to || '—'}`
  const id = typeof row.id === 'string' ? row.id : ''
  return id.slice(0, 8)
}

export class VoyageCatalogError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'VoyageCatalogError'
  }
}

/**
 * 실 API 구현 — `GET /api/v1/vessels/{id}/voyages` (`API_SPEC §3.1`).
 *
 * 페이지네이션은 따라가지 않는다. 셀렉트가 감당하는 규모를 넘어가면 그것은
 * 드롭다운이 아니라 검색 UI가 필요한 별개 문제다(`vesselCatalog.ts`와 같은 판단).
 */
export function createApiVoyageCatalog(baseUrl?: string): VoyageCatalogProvider {
  const base = baseUrl || DEFAULT_API_BASE_URL
  return {
    async listVoyages(vesselId: string) {
      let response: Response
      try {
        response = await fetch(`${base}/vessels/${vesselId}/voyages`, {
          method: 'GET',
          credentials: 'include',
          headers: csrfHeaders(),
        })
      } catch (cause) {
        throw new VoyageCatalogError('서버에 연결하지 못했습니다.', { cause })
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new VoyageCatalogError('로그인이 필요합니다.')
      }
      if (!response.ok) {
        throw new VoyageCatalogError('항차 목록을 불러오지 못했습니다.')
      }

      let body: { data?: unknown }
      try {
        body = (await response.json()) as { data?: unknown }
      } catch (cause) {
        throw new VoyageCatalogError('항차 목록 응답을 해석하지 못했습니다.', { cause })
      }

      const rows = Array.isArray(body.data) ? (body.data as VoyageListItem[]) : []
      return rows
        .filter((row) => typeof row.id === 'string')
        .map((row) => ({
          id: row.id as string,
          displayName: voyageDisplayName(row),
          status: typeof row.status === 'string' ? row.status : '',
        }))
    },
  }
}

/** demo ↔ 실 API 전환. 판단 기준은 다른 provider와 **같은 환경변수**다. */
export function createVoyageCatalog(
  env: ImportMetaEnv = import.meta.env,
): VoyageCatalogProvider {
  if (!shouldUseApi(env)) return createDemoVoyageCatalog()
  return createApiVoyageCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}
