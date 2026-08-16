import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  ScenarioComparisonError,
  type ScenarioComparisonErrorCode,
  type ScenarioComparisonProvider,
} from './provider'
import type {
  ScenarioComparisonRequest,
  ScenarioComparisonResponse,
  ScenarioResult,
} from './types'

/**
 * 기능② 실 API provider — `POST /scenarios/compare` (`API_SPEC §5.1` · #139).
 *
 * **화면 코드는 이 파일이 생겨도 바뀌지 않는다.** `#134`가 provider 인터페이스로
 * 경계를 그어 둔 것이 이 지점을 위해서였다 — 구현체만 갈아 끼운다.
 *
 * ## 요청 형태가 demo와 다르다
 *
 * demo provider는 API가 없던 시절에 만들어져 **총 연료량**(`base_fuel_ton`)을 받았다.
 * 실 API는 **일일 소모량**(`base_daily_foc_ton`)을 받는다 — 시나리오마다 소요시간이
 * 달라 총량으로는 감속 시나리오의 연료를 계산할 수 없기 때문이다.
 *
 * 변환은 **여기서 하지 않는다.** 총량 → 일일 환산은 항해 시간을 가정해야 하고,
 * 그 가정은 백엔드의 cubic speed model 소관이다. 대신 요청 타입이 API 계약을 따르게
 * 바꿨다(`types.ts`) — **API가 생긴 뒤에는 API가 계약이다.**
 *
 * ## 응답을 평탄화한다
 *
 * 서버는 `required_cii`·`transport_capacity_basis`를 **시나리오마다** 싣는다. 세
 * 시나리오가 같은 선박·같은 연도이므로 값이 같고, 화면은 하나만 필요하다. 첫
 * 시나리오의 값을 최상위로 올린다.
 *
 * ## Layer 1 값을 손대지 않는다
 *
 * 응답 JSON의 문자열을 그대로 넘긴다. `parseFloat`으로 되돌리면 `API_SPEC §1.7`이
 * 문자열 직렬화로 지킨 정밀도가 사라진다.
 */

/** `API_SPEC §1.4` 서버 오류 코드 → provider 코드. 기능①의 매핑과 같은 방식이다. */
const SERVER_CODE_MAP: Readonly<Record<string, ScenarioComparisonErrorCode>> = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  CALCULATION_ERROR: 'CALCULATION_ERROR',
  PARAMETER_ERROR: 'CALCULATION_ERROR',
  NOT_FOUND: 'UNSUPPORTED_VESSEL',
  INTERNAL_ERROR: 'CALCULATION_ERROR',
}

interface ServerCalculationBasis {
  ship_type?: string
  transport_capacity_basis?: string
}

interface ServerScenario {
  scenario_type: string
  scenario_name: string
  distance_nm: number
  speed_kn: number
  duration_hours: string
  fuel_ton: string
  co2_emission_ton: string
  attained_cii: string
  required_cii: string
  ratio_to_required: string
  estimated_rating: string
  risk_level: string
  next_worse_boundary_margin_ratio: string | null
  calculation_basis?: ServerCalculationBasis
}

interface ServerBody {
  data?: { scenarios?: ServerScenario[] }
  error?: {
    code?: string
    message?: string
    details?: Array<{ field?: string; message?: string }>
  }
}

function toScenario(raw: ServerScenario): ScenarioResult {
  return {
    scenario_type: raw.scenario_type as ScenarioResult['scenario_type'],
    scenario_name: raw.scenario_name,
    distance_nm: raw.distance_nm,
    speed_kn: raw.speed_kn,
    duration_hours: raw.duration_hours,
    fuel_ton: raw.fuel_ton,
    co2_emission_ton: raw.co2_emission_ton,
    attained_cii: raw.attained_cii,
    ratio_to_required: raw.ratio_to_required,
    estimated_rating: raw.estimated_rating as ScenarioResult['estimated_rating'],
    risk_level: raw.risk_level as ScenarioResult['risk_level'],
    next_worse_boundary_margin_ratio: raw.next_worse_boundary_margin_ratio,
  }
}

export function createApiScenarioProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): ScenarioComparisonProvider {
  return {
    async compare(
      request: ScenarioComparisonRequest,
    ): Promise<ScenarioComparisonResponse> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/scenarios/compare`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
            ...csrfHeaders(),
          },
          body: JSON.stringify({
            vessel_id: request.vessel_id,
            regulation_year: request.regulation_year,
            current_speed_kn: request.base_speed_kn,
            fuel_type: request.fuel_type,
            direct_distance_nm: request.base_distance_nm,
            base_daily_foc_ton: request.base_daily_foc_ton,
          }),
        })
      } catch (cause) {
        throw new ScenarioComparisonError(
          'CALCULATION_ERROR',
          '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.',
          undefined,
          { cause },
        )
      }

      // 세션 만료는 화면이 처리할 문제가 아니다 — 로그인으로 보낸다(기능①과 동일).
      if (response.status === 401) {
        redirectToLogin()
        throw new ScenarioComparisonError(
          'CALCULATION_ERROR',
          '세션이 만료되었습니다.',
        )
      }

      const body = (await response.json().catch(() => null)) as ServerBody | null

      if (!response.ok) {
        const serverCode = body?.error?.code ?? 'INTERNAL_ERROR'
        const detail = body?.error?.details?.[0]
        throw new ScenarioComparisonError(
          SERVER_CODE_MAP[serverCode] ?? 'CALCULATION_ERROR',
          body?.error?.message ?? `비교하지 못했습니다 (HTTP ${response.status}).`,
          detail?.field,
        )
      }

      const scenarios = body?.data?.scenarios ?? []
      if (scenarios.length === 0) {
        throw new ScenarioComparisonError(
          'CALCULATION_ERROR',
          '비교 결과가 비어 있습니다.',
        )
      }

      /*
       * 세 시나리오가 같은 선박·같은 연도라 아래 값들이 모두 같다. 첫 시나리오에서
       * 꺼내 최상위로 올린다 — 화면은 하나만 쓴다.
       */
      const first = scenarios[0]
      const basis = first.calculation_basis ?? {}

      return {
        scenarios: scenarios.map(toScenario),
        required_cii: first.required_cii,
        transport_capacity_basis:
          basis.transport_capacity_basis as ScenarioComparisonResponse['transport_capacity_basis'],
        ship_type: basis.ship_type ?? '',
        /*
         * 서버 응답에 선박 표시명이 없다. 화면이 제목에 쓰므로 빈 값을 두고,
         * 필요하면 호출부가 `GET /vessels/{id}`로 채운다 — 여기서 추가 호출을
         * 하면 provider가 두 엔드포인트에 묶인다.
         */
        vessel_display_name: '',
        warnings: [],
        disclaimer:
          '본 결과는 참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
      }
    },
  }
}
