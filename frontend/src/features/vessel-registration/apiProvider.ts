import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  VesselRegistrationError,
  type VesselRegistrationErrorCode,
  type VesselRegistrationProvider,
} from './provider'
import type { Vessel, VesselCreateRequest } from './types'

/**
 * 선박 등록 실 API provider — `POST /api/v1/vessels` (`API_SPEC §2.3`, #441).
 *
 * ## 응답을 가공하지 않는다
 *
 * `data`를 그대로 돌려준다. 등록 결과 표시는 **서버가 저장한 값**이어야 한다 — 화면이
 * 보낸 요청을 되보여 주면 서버가 채운 값(`id`·`is_cii_applicable_hint`·`created_at`)이
 * 빠지고, 무엇보다 **저장 실패를 성공으로 보이게** 만들 수 있다.
 *
 * ## CSRF 헤더가 필요하다
 *
 * 라우트에 `Depends(require_csrf)`가 붙어 있다(`api/routes/vessels.py:135`). 쿠키의
 * csrf 원문을 `X-CSRF-Token`으로 옮겨 싣는다(`API_SPEC §1.2`) — 붙이지 않으면 403이
 * 나는데, 그 실패는 입력 오류처럼 보이지 않아 원인을 찾기 어렵다.
 */

/** 서버 오류 코드(`API_SPEC §1.4`) → 화면 오류 코드. */
const SERVER_CODE_MAP: Readonly<Record<string, VesselRegistrationErrorCode>> = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  /** 중복 IMO. `#286`이 `PARAMETER_ERROR`와 분리한 전용 코드다. */
  CONFLICT: 'CONFLICT',
  /** 같은 409이지만 규정 파라미터 문제다 — 사용자가 입력으로 고칠 수 없다. */
  PARAMETER_ERROR: 'REGISTRATION_ERROR',
  INTERNAL_ERROR: 'REGISTRATION_ERROR',
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

/**
 * 서버 오류 응답을 `VesselRegistrationError`로 옮긴다.
 *
 * `details[0]`만 쓴다 — 오류 객체가 필드 하나만 담는다. 화면 검증(`validateForm`)이
 * 전 필드를 앞에서 잡으므로 여러 필드가 동시에 틀린 채로 여기 오기 어렵다.
 */
export function toVesselRegistrationError(
  status: number,
  body: unknown,
): VesselRegistrationError {
  const error = ((body ?? {}) as ServerErrorBody).error
  if (!error || typeof error.code !== 'string') {
    return new VesselRegistrationError(
      'REGISTRATION_ERROR',
      `${MALFORMED_ERROR_MESSAGE} (HTTP ${status})`,
    )
  }
  return new VesselRegistrationError(
    SERVER_CODE_MAP[error.code] ?? 'REGISTRATION_ERROR',
    error.message ?? MALFORMED_ERROR_MESSAGE,
    error.details?.[0]?.field,
  )
}

export interface ApiProviderOptions {
  baseUrl?: string
  /** `#104` API Key가 적용된 경우에만 주입한다. 빈 값은 헤더를 붙이지 않는다. */
  apiKey?: string
  /** 테스트에서 갈아 끼우기 위한 주입점. */
  fetchImpl?: typeof fetch
}

export function createApiVesselRegistrationProvider(
  options: ApiProviderOptions = {},
): VesselRegistrationProvider {
  const baseUrl = options.baseUrl ?? DEFAULT_API_BASE_URL
  const doFetch = options.fetchImpl ?? globalThis.fetch

  return {
    async register(request: VesselCreateRequest): Promise<Vessel> {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (options.apiKey) headers['X-API-Key'] = options.apiKey
      Object.assign(headers, csrfHeaders())

      let response: Response
      try {
        response = await doFetch(`${baseUrl}/vessels`, {
          method: 'POST',
          credentials: 'include',
          headers,
          body: JSON.stringify(request),
        })
      } catch (cause) {
        // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
        throw new VesselRegistrationError(
          'REGISTRATION_ERROR',
          NETWORK_ERROR_MESSAGE,
          undefined,
          { cause },
        )
      }

      // 오류 응답에도 본문이 있어야 필드를 꺼낼 수 있으므로 파싱을 먼저 시도한다.
      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        body = null
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new VesselRegistrationError('REGISTRATION_ERROR', SESSION_EXPIRED_MESSAGE)
      }
      if (!response.ok) {
        throw toVesselRegistrationError(response.status, body)
      }

      const data = (body as { data?: unknown } | null)?.data
      if (data === null || data === undefined || typeof data !== 'object') {
        // 201을 받았으나 본문이 계약과 다르다. **성공으로 처리하지 않는다** — 등록됐는지
        // 알 수 없는 상태를 「등록 완료」로 보이면 사용자가 같은 배를 두 번 등록한다.
        throw new VesselRegistrationError('REGISTRATION_ERROR', MALFORMED_ERROR_MESSAGE)
      }
      return data as Vessel
    },
  }
}
