import { VoyageCiiError, type VoyageCiiErrorCode, type VoyageCiiProvider } from './provider'
import type { VoyageCiiRequest, VoyageCiiResponse } from './types'

/**
 * 기능① 실 API provider (#138).
 *
 * **화면 코드는 이 파일이 생겨도 바뀌지 않는다.** `#134`가 `VoyageCiiProvider`
 * 인터페이스로 경계를 그어 둔 것이 이 지점을 위해서였다 — 구현체만 갈아 끼운다.
 *
 * ## 서버 오류를 `VoyageCiiError`로 옮긴다
 *
 * 화면은 계속 `VoyageCiiError`만 안다. 서버 응답 형태(`API_SPEC §1.3.2`)를 화면이
 * 직접 다루면 provider 경계가 무너지고, demo provider로 되돌릴 수 없게 된다.
 *
 * ```
 * { "error": { "code", "message", "details": [{ field, field_label, message }] },
 *   "meta": { "request_id", "timestamp" } }
 * ```
 *
 * `details[0].field`가 곧 `VoyageCiiError.field`이며, 그 값이 `fuel_uses[0].fuel_ton`
 * 형태라 `#135`의 `FIELD` 상수와 그대로 맞는다.
 *
 * ## Layer 1 값을 손대지 않는다
 *
 * 응답 JSON을 그대로 넘긴다. `parseFloat`·`Number`로 되돌리면 `API_SPEC §1.7`이
 * 문자열 직렬화로 지킨 정밀도가 사라진다. **재직렬화도 하지 않는다.**
 */

/** 기본 API base URL. 개발 서버는 프록시를 거치므로 상대 경로가 맞다. */
export const DEFAULT_API_BASE_URL = '/api/v1'

/**
 * 서버 오류 코드 → provider 오류 코드.
 *
 * 서버는 `API_SPEC §1.4`의 코드를 쓰고 화면은 `#134`가 정한 코드를 쓴다. 두 집합이
 * 완전히 겹치지 않으므로 매핑이 필요하다 — 겹치는 것은 그대로 두고, 서버에만 있는
 * 것은 화면이 아는 코드로 옮긴다.
 *
 * | 서버 | 화면 | 이유 |
 * |---|---|---|
 * | `PARAMETER_ERROR` | `CALCULATION_ERROR` | 화면에 `PARAMETER_ERROR`가 없다. 사용자가 입력으로 고칠 수 없다는 성질은 같다 |
 * | `NOT_FOUND` | `UNSUPPORTED_VESSEL` | 기능①에서 404가 나는 경로는 선박 조회뿐이다 |
 * | `INTERNAL_ERROR` | `CALCULATION_ERROR` | 화면에 서버 오류 코드가 없다. 메시지로 구분한다 |
 */
const SERVER_CODE_MAP: Readonly<Record<string, VoyageCiiErrorCode>> = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  CALCULATION_ERROR: 'CALCULATION_ERROR',
  PARAMETER_ERROR: 'CALCULATION_ERROR',
  NOT_FOUND: 'UNSUPPORTED_VESSEL',
  INTERNAL_ERROR: 'CALCULATION_ERROR',
}

/** `API_SPEC §1.3.2` 오류 응답. 서버가 이 형태를 보장한다(#116). */
interface ServerErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Array<{ field?: string; field_label?: string; message?: string }>
  }
}

/**
 * 사용자에게 보일 네트워크 장애 문구.
 *
 * `fetch`가 던지는 `TypeError: Failed to fetch`를 그대로 보이면 원인이 전달되지 않는다.
 */
export const NETWORK_ERROR_MESSAGE =
  '서버에 연결하지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해 주세요.'

/** 서버가 오류 응답 형태를 지키지 못했을 때의 문구. */
export const MALFORMED_ERROR_MESSAGE = '서버 응답을 해석하지 못했습니다.'

/**
 * 서버 오류 응답을 `VoyageCiiError`로 옮긴다.
 *
 * `details[0]`만 쓴다 — `VoyageCiiError`가 필드 하나만 담기 때문이다. 나머지는
 * `message`에 남지 않으므로, **여러 필드가 동시에 틀린 경우 화면은 첫 필드만 표시**한다.
 * `#135`의 클라이언트 검증이 그 앞에서 전 필드를 잡으므로 실제로 도달하기 어렵다.
 */
export function toVoyageCiiError(status: number, body: unknown): VoyageCiiError {
  const parsed = (body ?? {}) as ServerErrorBody
  const error = parsed.error
  if (!error || typeof error.code !== 'string') {
    return new VoyageCiiError(
      'CALCULATION_ERROR',
      `${MALFORMED_ERROR_MESSAGE} (HTTP ${status})`,
    )
  }

  const code = SERVER_CODE_MAP[error.code] ?? 'CALCULATION_ERROR'
  const message = error.message ?? MALFORMED_ERROR_MESSAGE
  const field = error.details?.[0]?.field
  return new VoyageCiiError(code, message, field)
}

export interface ApiProviderOptions {
  /** base URL. 기본값은 상대 경로 `/api/v1` — 개발 서버 프록시를 탄다. */
  baseUrl?: string
  /** `#104` API Key가 적용된 경우 주입할 키. 없으면 헤더를 붙이지 않는다. */
  apiKey?: string
  /** 테스트에서 갈아 끼우기 위한 주입점. */
  fetchImpl?: typeof fetch
}

/**
 * 실 API를 호출하는 provider를 만든다.
 *
 * `#104`(API Key)가 적용되지 않은 지금은 `apiKey`가 없으면 헤더 자체를 붙이지 않는다 —
 * 빈 값을 보내면 서버가 「키가 있는데 틀렸다」로 볼 수 있다.
 */
export function createApiProvider(options: ApiProviderOptions = {}): VoyageCiiProvider {
  const baseUrl = options.baseUrl ?? DEFAULT_API_BASE_URL
  const doFetch = options.fetchImpl ?? globalThis.fetch

  return {
    async estimate(request: VoyageCiiRequest): Promise<VoyageCiiResponse> {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (options.apiKey) headers['X-API-Key'] = options.apiKey

      let response: Response
      try {
        response = await doFetch(`${baseUrl}/calculations/voyage-cii`, {
          method: 'POST',
          headers,
          body: JSON.stringify(request),
        })
      } catch (cause) {
        // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
        throw new VoyageCiiError('CALCULATION_ERROR', NETWORK_ERROR_MESSAGE, undefined, {
          cause,
        })
      }

      // 본문 파싱을 먼저 시도한다 — 오류 응답에도 본문이 있어야 필드를 꺼낼 수 있다.
      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        body = null
      }

      if (!response.ok) {
        throw toVoyageCiiError(response.status, body)
      }
      if (body === null || typeof body !== 'object') {
        throw new VoyageCiiError('CALCULATION_ERROR', MALFORMED_ERROR_MESSAGE)
      }
      // Layer 1 값을 손대지 않고 그대로 넘긴다.
      return body as VoyageCiiResponse
    },
  }
}
