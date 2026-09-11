import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import type {
  AnnualSimulationProvider,
  AnnualSimulationRequest,
  AnnualSimulationResult,
  SnapshotVoyage,
} from './types'

/**
 * 기능③ 실 API provider — `POST /annual-simulations` (`API_SPEC §6.1`, #442) ·
 * `POST /annual-simulations/{id}/reproduce` (`§6.4`, #776).
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

  /*
   * `run`과 `reproduce`는 **같은 봉투**를 받는다(`API_SPEC §6.4` — 「§6.1의 응답과
   * 동일」). 파싱을 한 곳에 두어 둘이 갈리지 않게 한다 — 봉투 규칙(`#752`)을 한쪽에만
   * 고치면 재현 결과만 `calculation_run_id`가 빠진 채 화면에 닿는다.
   */
  async function post(path: string, body?: unknown): Promise<AnnualSimulationResult> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (options.apiKey) headers['X-API-Key'] = options.apiKey
    // CSRF — 서버가 검증하는 것은 헤더뿐이다(`API_SPEC §1.2`).
    Object.assign(headers, csrfHeaders())

    let response: Response
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method: 'POST',
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
    } catch (cause) {
      // fetch는 네트워크 실패에서만 reject한다. HTTP 4xx·5xx는 정상 resolve다.
      throw new AnnualSimulationError(NETWORK_ERROR_MESSAGE, undefined, { cause })
    }

    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      parsed = null
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new AnnualSimulationError(SESSION_EXPIRED_MESSAGE)
    }
    if (!response.ok) throw toAnnualSimulationError(response.status, parsed)

    const envelope = parsed as {
      data?: unknown
      calculation_run_id?: unknown
      warnings?: unknown
    } | null
    const data = envelope?.data
    if (data === null || typeof data !== 'object') {
      throw new AnnualSimulationError(MALFORMED_ERROR_MESSAGE)
    }

    // `calculation_run_id`와 `warnings`는 **`data` 밖**에 있다 (`API_SPEC §1.3.1`,
    // `#752`). 기능①·②도 최상위로 낸다. 화면 타입(`AnnualSimulationResult`)은
    // 그대로 두고 **여기서 합친다** — provider 경계가 이런 용도로 있다.
    //
    // 값이 없으면 던진다. 조용히 빈 배열·빈 문자열로 채우면 「경고가 없다」와
    // 「경고를 받지 못했다」가 구분되지 않는데, 앞의 것은 정상이고 뒤의 것은 계약
    // 위반이다.
    const runId = envelope?.calculation_run_id
    const warnings = envelope?.warnings
    if (typeof runId !== 'string' || !Array.isArray(warnings)) {
      throw new AnnualSimulationError(MALFORMED_ERROR_MESSAGE)
    }

    // Layer 1 값을 손대지 않고 그대로 넘긴다.
    return {
      ...(data as Omit<AnnualSimulationResult, 'calculation_run_id' | 'warnings'>),
      calculation_run_id: runId,
      warnings: warnings as string[],
    }
  }

  /** 조회(GET) — 스냅샷 항차 (`§6.3` · #992). 봉투는 `{data: [...]}`다. */
  async function getSnapshotVoyages(simulationId: string): Promise<SnapshotVoyage[]> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (options.apiKey) headers['X-API-Key'] = options.apiKey
    let response: Response
    try {
      response = await doFetch(
        `${baseUrl}/annual-simulations/${encodeURIComponent(simulationId)}/snapshot-voyages`,
        { method: 'GET', credentials: 'include', headers },
      )
    } catch (cause) {
      throw new AnnualSimulationError(NETWORK_ERROR_MESSAGE, undefined, { cause })
    }
    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      parsed = null
    }
    if (response.status === 401) {
      redirectToLogin()
      throw new AnnualSimulationError(SESSION_EXPIRED_MESSAGE)
    }
    if (!response.ok) throw toAnnualSimulationError(response.status, parsed)
    const rows = (parsed as { data?: unknown } | null)?.data
    // 빈 배열로 삼키지 않는다 — 「쓴 항차가 없다」와 「못 받았다」가 구분되지 않는다.
    if (!Array.isArray(rows)) throw new AnnualSimulationError(MALFORMED_ERROR_MESSAGE)
    return rows as SnapshotVoyage[]
  }

  return {
    run: (request: AnnualSimulationRequest) => post('/annual-simulations', request),
    snapshotVoyages: getSnapshotVoyages,
    // 본문이 없다 — 조건은 서버가 원본 실행에서 읽는다(`API_SPEC §6.4`). 화면이 조건을
    // 다시 보내면 폼을 고친 뒤 누른 경우 **원본이 아닌 조건**으로 재현을 시도하게 된다.
    reproduce: (simulationId: string) =>
      post(`/annual-simulations/${encodeURIComponent(simulationId)}/reproduce`),
  }
}
