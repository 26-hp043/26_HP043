import { csrfHeaders, redirectToLogin } from '../../auth/session'
import type {
  AnnualSimulationProvider,
  AnnualSimulationRequest,
  AnnualSimulationResult,
} from './types'

/**
 * 기능③ 실 API provider — `POST /annual-simulations` (`API_SPEC §6.1`, #442).
 *
 * ## 왜 이 파일이 늦게 생겼는가
 *
 * 엔진(`#63`)과 API(`#64`)가 2026-08-17에 들어왔는데 화면은 `#157`의 목업 그대로였다.
 * **화면 파일이 존재해서 목록상 빠진 게 없어 보였고**, 나머지 8개 feature가 전부 실
 * API에 연결돼 있어 이것만 예외인 것이 눈에 띄지 않았다.
 *
 * ## Layer 1 값을 손대지 않는다
 *
 * 응답을 그대로 넘긴다. 재직렬화도 하지 않는다 — `API_SPEC §1.7`이 문자열 직렬화로
 * 지킨 정밀도가 `JSON.parse` → `JSON.stringify` 왕복에서 사라질 수 있다.
 *
 * ## 오류를 화면 문구로 옮긴다
 *
 * 기능①의 `apiProvider`와 같은 구조다. 서버 응답 형태(`API_SPEC §1.3.2`)를 화면이 직접
 * 다루면 provider 경계가 무너지고 demo provider로 되돌릴 수 없게 된다.
 */

/** 기본 API base URL. 개발 서버는 프록시를 거치므로 상대 경로가 맞다. */
export const DEFAULT_API_BASE_URL = '/api/v1'

export const NETWORK_ERROR_MESSAGE =
  '서버에 연결하지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해 주세요.'

export const MALFORMED_ERROR_MESSAGE = '서버 응답을 해석하지 못했습니다.'

export const SESSION_EXPIRED_MESSAGE = '로그인이 만료되었습니다. 다시 로그인해 주세요.'

/** 기능③ 실행 실패. 화면은 이 오류만 안다. */
/**
 * ⚠️ **`export`를 떼지 않는다 (#594).** 지금은 어느 화면도 종류로 잡지 않지만
 * (`AnnualSimulation.tsx`가 `error instanceof Error`로만 본다), 이 저장소의 provider
 * 오류 계약은 넷이 같은 모양이다 — `VoyageError` · `NotUnderwayError` ·
 * `ParametersError` · `FuelCatalogError`. 이 하나만 감추면 다음 사람이 **이
 * provider만 다른 규칙인 줄** 안다.
 */
export class AnnualSimulationError extends Error {
  /** 서버가 지목한 필드(`details[0].field`). 없으면 `undefined`. */
  readonly field?: string

  constructor(message: string, field?: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'AnnualSimulationError'
    this.field = field
  }
}

interface ServerErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Array<{ field?: string; field_label?: string; message?: string }>
  }
}

/**
 * 서버 오류를 화면 오류로 옮긴다.
 *
 * **서버 메시지를 고쳐 쓰지 않는다.** `PRD §12.8`이 거부 사유를 문구로 규정하고
 * (`target_rating = E` · 잔여 항차 200개 초과) 서버가 그 문구를 낸다 — 화면이 다시 쓰면
 * 두 문구가 갈린다.
 */
export function toAnnualSimulationError(status: number, body: unknown): AnnualSimulationError {
  const parsed = (body ?? {}) as ServerErrorBody
  const error = parsed.error
  if (!error || typeof error.message !== 'string') {
    return new AnnualSimulationError(`${MALFORMED_ERROR_MESSAGE} (HTTP ${status})`)
  }
  return new AnnualSimulationError(error.message, error.details?.[0]?.field)
}

export interface ApiProviderOptions {
  baseUrl?: string
  apiKey?: string
  /** 테스트에서 갈아 끼우기 위한 주입점. */
  fetchImpl?: typeof fetch
}

/** 실 API를 호출하는 provider를 만든다. */
export function createApiAnnualSimulationProvider(
  options: ApiProviderOptions = {},
): AnnualSimulationProvider {
  const baseUrl = options.baseUrl ?? DEFAULT_API_BASE_URL
  const doFetch = options.fetchImpl ?? globalThis.fetch

  return {
    async run(request: AnnualSimulationRequest): Promise<AnnualSimulationResult> {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (options.apiKey) headers['X-API-Key'] = options.apiKey
      // CSRF — 서버가 검증하는 것은 헤더뿐이다(`API_SPEC §1.2`).
      Object.assign(headers, csrfHeaders())

      let response: Response
      try {
        response = await doFetch(`${baseUrl}/annual-simulations`, {
          method: 'POST',
          headers,
          body: JSON.stringify(request),
        })
      } catch (cause) {
        // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
        throw new AnnualSimulationError(NETWORK_ERROR_MESSAGE, undefined, { cause })
      }

      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        body = null
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new AnnualSimulationError(SESSION_EXPIRED_MESSAGE)
      }
      if (!response.ok) throw toAnnualSimulationError(response.status, body)

      const data = (body as { data?: unknown } | null)?.data
      if (data === null || typeof data !== 'object') {
        throw new AnnualSimulationError(MALFORMED_ERROR_MESSAGE)
      }
      // Layer 1 값을 손대지 않고 그대로 넘긴다.
      return data as AnnualSimulationResult
    },
  }
}
