import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  VesselManagementError,
  type VesselManagementErrorCode,
  type VesselManagementProvider,
  type VesselPage,
  type VesselUpdateRequest,
} from './provider'
import type { Vessel } from '../vessel-registration/types'

/**
 * 선박 관리 실 API provider (#510).
 *
 * - 목록 `GET /api/v1/vessels` (`API_SPEC §2.1`)
 * - 수정 `PATCH /api/v1/vessels/{id}` (`API_SPEC §2.4`)
 * - 삭제 `DELETE /api/v1/vessels/{id}` (`API_SPEC §2.5`)
 *
 * ## `imo_number`를 수정 요청에 싣지 않는다
 *
 * 서버 `VesselUpdateRequest`가 `extra="forbid"`이고 `imo_number` 필드를 **아예 갖지
 * 않는다**(`api/schemas/vessel.py:47`). 실어 보내면 422가 나는데, 그 실패는 입력
 * 오류처럼 보이지 않아 원인을 찾기 어렵다. 타입 단계에서 막는다.
 *
 * ## 삭제 응답은 204가 아니다
 *
 * `API_SPEC §2.5`가 200 OK + `data.deleted = true`를 규정한다
 * (`routes/vessels.py:210` docstring). 본문을 읽되 **`deleted`를 다시 검사하지 않는다** —
 * 서버가 200을 준 것이 곧 soft delete 성공이고, 화면이 판정을 겹쳐 두면 계약이 바뀔 때
 * 두 곳을 고쳐야 한다.
 */

/** 서버 오류 코드(`API_SPEC §1.4`) → 화면 오류 코드. */
const SERVER_CODE_MAP: Readonly<Record<string, VesselManagementErrorCode>> = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  /** 중복 IMO. 수정은 IMO를 못 바꾸므로 실제로는 삭제 경로에서만 나온다. */
  CONFLICT: 'CONFLICT',
  PARAMETER_ERROR: 'MANAGEMENT_ERROR',
  INTERNAL_ERROR: 'MANAGEMENT_ERROR',
}

/** `API_SPEC §1.3.2` 오류 응답. */
interface ServerErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Array<{ field?: string; field_label?: string; message?: string }>
  }
}

export const NETWORK_ERROR_MESSAGE =
  '서버에 연결하지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해 주세요.'

export const MALFORMED_ERROR_MESSAGE = '서버 응답을 해석하지 못했습니다.'

export const SESSION_EXPIRED_MESSAGE = '로그인이 만료되었습니다. 다시 로그인해 주세요.'

/** 서버 오류 응답을 `VesselManagementError`로 옮긴다. */
export function toVesselManagementError(
  status: number,
  body: unknown,
): VesselManagementError {
  const error = ((body ?? {}) as ServerErrorBody).error
  if (!error || typeof error.code !== 'string') {
    return new VesselManagementError(
      'MANAGEMENT_ERROR',
      `${MALFORMED_ERROR_MESSAGE} (HTTP ${status})`,
    )
  }
  return new VesselManagementError(
    SERVER_CODE_MAP[error.code] ?? 'MANAGEMENT_ERROR',
    error.message ?? MALFORMED_ERROR_MESSAGE,
    error.details?.[0]?.field,
  )
}

export interface ApiProviderOptions {
  baseUrl?: string
  apiKey?: string
  fetchImpl?: typeof fetch
}

/**
 * `meta`에서 페이지네이션 정보를 꺼낸다.
 *
 * 값이 없거나 형이 다르면 **「더 없음」으로 읽는다.** 커서를 지어내면 같은 페이지를
 * 무한히 다시 부른다.
 */
export function readPageMeta(body: unknown): { nextCursor: string | null; hasMore: boolean } {
  const meta = (body as { meta?: Record<string, unknown> } | null)?.meta
  const cursor = meta?.next_cursor
  const more = meta?.has_more
  return {
    nextCursor: typeof cursor === 'string' && cursor !== '' ? cursor : null,
    hasMore: more === true,
  }
}

export function createApiVesselManagementProvider(
  options: ApiProviderOptions = {},
): VesselManagementProvider {
  const baseUrl = options.baseUrl ?? DEFAULT_API_BASE_URL
  const doFetch = options.fetchImpl ?? globalThis.fetch

  /** 공통 요청 — 네트워크 실패·401·오류 본문 처리를 한 곳에 둔다. */
  async function request(
    path: string,
    init: RequestInit & { write?: boolean },
  ): Promise<unknown> {
    const headers: Record<string, string> = {}
    if (init.body !== undefined) headers['Content-Type'] = 'application/json'
    if (options.apiKey) headers['X-API-Key'] = options.apiKey
    // 쓰기 라우트에는 `Depends(require_csrf)`가 붙어 있다(`routes/vessels.py`).
    // 붙이지 않으면 403이 나는데 그 실패는 입력 오류처럼 보이지 않는다.
    if (init.write) Object.assign(headers, csrfHeaders())

    let response: Response
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        ...init,
        credentials: 'include',
        headers: { ...headers, ...(init.headers as Record<string, string> | undefined) },
      })
    } catch (cause) {
      // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
      throw new VesselManagementError('MANAGEMENT_ERROR', NETWORK_ERROR_MESSAGE, undefined, {
        cause,
      })
    }

    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new VesselManagementError('MANAGEMENT_ERROR', SESSION_EXPIRED_MESSAGE)
    }
    if (!response.ok) throw toVesselManagementError(response.status, body)
    return body
  }

  return {
    async list(listOptions = {}): Promise<VesselPage> {
      const params = new URLSearchParams()
      if (listOptions.cursor) params.set('cursor', listOptions.cursor)
      if (listOptions.search) params.set('search', listOptions.search)
      const query = params.toString()
      const body = await request(`/vessels${query ? `?${query}` : ''}`, { method: 'GET' })

      const data = (body as { data?: unknown } | null)?.data
      if (!Array.isArray(data)) {
        // 목록 자리에 배열이 아닌 것이 오면 **빈 목록으로 처리하지 않는다** — 「선박이
        // 없다」와 「목록을 못 읽었다」는 사용자가 취할 행동이 다르다.
        throw new VesselManagementError('MANAGEMENT_ERROR', MALFORMED_ERROR_MESSAGE)
      }
      return { vessels: data as Vessel[], ...readPageMeta(body) }
    },

    async update(vesselId: string, patch: VesselUpdateRequest): Promise<Vessel> {
      const body = await request(`/vessels/${vesselId}`, {
        method: 'PATCH',
        write: true,
        body: JSON.stringify(patch),
      })
      const data = (body as { data?: unknown } | null)?.data
      if (data === null || data === undefined || typeof data !== 'object') {
        // 200을 받았으나 본문이 계약과 다르다. 성공으로 처리하면 화면이 **저장되지
        // 않은 값**을 저장된 것으로 보여 준다.
        throw new VesselManagementError('MANAGEMENT_ERROR', MALFORMED_ERROR_MESSAGE)
      }
      return data as Vessel
    },

    async remove(vesselId: string): Promise<void> {
      await request(`/vessels/${vesselId}`, { method: 'DELETE', write: true })
    },
  }
}
