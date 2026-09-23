import { csrfHeaders, redirectToLogin } from '../auth/session'
import { MAX_PAGES, nextCursorOf, pagedUrl } from './catalogPaging'
import { DEFAULT_API_BASE_URL } from '../api/base'
import { API_BASE_URL_ENV_KEY } from '../features/voyage-cii/providerSelection'
import { portDisplayName, type SamplePort } from '../features/ports/samplePorts'

/**
 * 항차 선택지의 데이터 경계 (#512).
 *
 * `vesselCatalog.ts`(#236)와 같은 구성이다 — 화면은 출처를 알지 않는다.
 *
 * ## 종전 demo 갈래는 빈 목록이었다 (#542가 제거)
 *
 * 고정표(`referenceTable.ts`)는 계산 입력을 담고 있을 뿐 항차를 갖지 않아
 * **빈 목록**을 돌려줬다 — 상단바가 「항차 없음」으로 표시하며,
 * 그것이 사실이다.
 *
 * ## 구간 표시는 저장 코드가 아니라 보이는 이름이다 (#1812)
 *
 * `departure_port_name`·`arrival_port_name`은 항차에 **저장되는** 코드(`BUSAN` 등)다.
 * `portDisplayName`(`features/ports/samplePorts.ts`)이 이미 「보이는 이름」 변환을
 * 갖고 있으므로 여기서 다시 만들지 않고 그대로 부른다.
 */

/** 상단바 셀렉트가 쓰는 최소 형태. */
export interface VoyageOption {
  id: string
  /** 항차 번호. 없으면 출발항 → 도착항으로 대신한다. */
  displayName: string
  status: string
}

export interface VoyageCatalogProvider {
  listVoyages(vesselId: string, ports: readonly SamplePort[]): Promise<VoyageOption[]>
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
 *
 * 구간에 쓰는 항구 이름은 저장 코드가 아니라 `portDisplayName`이 돌려주는 보이는
 * 이름이다(#1812). 목록에 없는 항구는 입력한 그대로 나온다 — `portDisplayName` 참조.
 */
export function voyageDisplayName(row: VoyageListItem, ports: readonly SamplePort[]): string {
  if (typeof row.voyage_no === 'string' && row.voyage_no.trim() !== '') return row.voyage_no
  const from =
    typeof row.departure_port_name === 'string' ? portDisplayName(ports, row.departure_port_name) : ''
  const to =
    typeof row.arrival_port_name === 'string' ? portDisplayName(ports, row.arrival_port_name) : ''
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
 * **페이지네이션을 끝까지 따른다** (`#1073` · `layout/catalogPaging.ts`). 종전에는 첫 페이지만
 * 받아 서버 기본 `limit` 20에서 잘렸다 — `#627`이 범위에 넣고 처리하지 않은 곳이다.
 * 셀렉트가 감당하는 규모(5,000건)를 넘어가면 검색 UI가 필요한 별개 문제다.
 */
export function createApiVoyageCatalog(baseUrl?: string): VoyageCatalogProvider {
  const base = baseUrl || DEFAULT_API_BASE_URL
  return {
    async listVoyages(vesselId: string, ports: readonly SamplePort[]) {
      // 커서를 끝까지 따른다 (#1073) — 종전에는 첫 페이지(20건)만 받아 21번째 항차를 고를 수 없었다.
      const rows: VoyageListItem[] = []
      let cursor: string | null = null
      for (let page = 0; page < MAX_PAGES; page += 1) {
        let response: Response
        try {
          response = await fetch(pagedUrl(`${base}/vessels/${vesselId}/voyages`, cursor), {
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
        if (Array.isArray(body.data)) rows.push(...(body.data as VoyageListItem[]))
        cursor = nextCursorOf(body)
        if (cursor === null) break
      }
      return rows
        .filter((row) => typeof row.id === 'string')
        .map((row) => ({
          id: row.id as string,
          displayName: voyageDisplayName(row, ports),
          status: typeof row.status === 'string' ? row.status : '',
        }))
    },
  }
}

/** 환경에 맞는 카탈로그를 만든다. 데모 갈래는 `#542`가 없앴다. */
export function createVoyageCatalog(
  env: ImportMetaEnv = import.meta.env,
): VoyageCatalogProvider {
  return createApiVoyageCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}
