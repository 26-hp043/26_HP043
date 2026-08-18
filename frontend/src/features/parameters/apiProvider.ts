import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'

/**
 * 규제 파라미터 조회 — `API_SPEC §7.1~§7.4` (`#444`).
 *
 * ## 왜 별도 모듈인가
 *
 * 연료 선택지는 **여러 화면이 필요로 한다** — 정박 구간 입력(`#370`), 선박 등록
 * (`#441`), 앞으로의 항차 입력. 기능별 provider 안에 두면 화면마다 같은 조회가
 * 다시 만들어지고, `#444`가 고친 상태(관계없는 엔드포인트의 `meta`에 목록을 실어
 * 나르던 우회)가 형태만 바꿔 되살아난다.
 *
 * ## 값을 가공하지 않는다
 *
 * `cf`는 서버가 문자열로 준다(`API_SPEC §1.7`). `Number`로 되돌리면 정밀도가 깎이고,
 * 그 차이는 등급 경계 근처에서만 드러나 발견이 늦다. **표시도 계산도 문자열 그대로**
 * 다루고, 필요한 곳에서만 비교한다.
 */

export class ParametersError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'ParametersError'
  }
}

/** `API_SPEC §7.2` 연료 종류 1건. */
export interface FuelTypeOption {
  code: string
  displayName: string
  /** **문자열이다.** Layer 1 표기 규칙 (`API_SPEC §1.7`). */
  cf: string
  unit: string
  isActive: boolean
}

interface ServerFuelType {
  code?: unknown
  display_name?: unknown
  cf?: unknown
  unit?: unknown
  is_active?: unknown
}

export interface ParametersProvider {
  listFuelTypes(): Promise<FuelTypeOption[]>
}

export function createApiParametersProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): ParametersProvider {
  return {
    async listFuelTypes(): Promise<FuelTypeOption[]> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/parameters/fuel-types`, {
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
        })
      } catch (cause) {
        throw new ParametersError('서버에 연결하지 못했습니다.', { cause })
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new ParametersError('세션이 만료되었습니다.')
      }
      if (!response.ok) {
        throw new ParametersError(`연료 목록을 불러오지 못했습니다 (HTTP ${response.status}).`)
      }

      const body = (await response.json().catch(() => null)) as { data?: unknown } | null
      const rows = Array.isArray(body?.data) ? (body?.data as ServerFuelType[]) : []
      return rows.filter((row) => typeof row.code === 'string').map(toFuelTypeOption)
    },
  }
}

function toFuelTypeOption(raw: ServerFuelType): FuelTypeOption {
  return {
    code: raw.code as string,
    // 표시 이름이 없으면 코드를 쓴다 — 빈 항목이 셀렉트에 뜨는 것보다 낫다.
    displayName: typeof raw.display_name === 'string' ? raw.display_name : (raw.code as string),
    cf: typeof raw.cf === 'string' ? raw.cf : '',
    unit: typeof raw.unit === 'string' ? raw.unit : '',
    // 기본 조회는 활성만 돌려주므로, 값이 없으면 활성으로 본다.
    isActive: raw.is_active !== false,
  }
}
