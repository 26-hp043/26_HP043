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

interface ServerRegulationYear {
  year?: unknown
}

export interface ParametersProvider {
  listFuelTypes(): Promise<FuelTypeOption[]>
  /**
   * 규정 연도 목록 (`API_SPEC §7.1`). 오름차순.
   *
   * **연도 숫자만 돌려준다.** 응답에는 `z_factor_percent`·`effective_from`·
   * `source_ref`·`version`도 실리지만, 화면이 쓰는 것은 선택지의 연도뿐이다.
   * Z계수는 `required_cii`를 서버가 계산할 때 쓰는 값이라 화면이 알 필요가 없고,
   * 들고 오면 **화면이 계산에 쓸 수 있는 상태**가 된다 — `referenceTable.ts`가
   * *"이 값으로 다른 선박·연도를 계산하지 말 것"* 으로 막아 둔 것과 같은 이유다.
   *
   * ## 선종 인자를 받지 않는다
   *
   * `regulation_year` 테이블에는 `ship_type` 컬럼이 없다(`DB_SCHEMA §3.1`).
   * Z계수는 전 선종 공통이므로 선박마다 목록이 갈리지 않는다. 선종별로 갈리는
   * 것은 기준선·등급 경계이며 그건 계산 시점에 서버가 판정한다.
   */
  listRegulationYears(): Promise<number[]>
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

    async listRegulationYears(): Promise<number[]> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/parameters/regulation-years`, {
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
        throw new ParametersError(`규제연도 목록을 불러오지 못했습니다 (HTTP ${response.status}).`)
      }

      const body = (await response.json().catch(() => null)) as { data?: unknown } | null
      const rows = Array.isArray(body?.data) ? (body?.data as ServerRegulationYear[]) : []
      // 서버가 정렬을 보장한다는 계약은 없다. 셀렉트 순서는 화면이 정한다.
      return rows
        .map((row) => row.year)
        .filter((year): year is number => typeof year === 'number' && Number.isInteger(year))
        .sort((a, b) => a - b)
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
