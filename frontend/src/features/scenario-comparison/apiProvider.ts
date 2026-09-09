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
  /*
   * `API_SPEC §5.1` — 응답 **최상위**에 실린다(`data` 안이 아니다).
   * `routes/scenarios.py`가 서비스 dict를 그대로 돌려주고 `meta`만 덧붙인다.
   */
  warnings?: string[]
  disclaimer?: string
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
          /*
           * 선택 입력 5종은 **`undefined`면 키가 사라진다** — `JSON.stringify`가
           * `undefined` 값을 가진 키를 통째로 뺀다. 서버 스키마가
           * `extra="forbid"`이면서 각 필드의 기본을 `None`으로 두므로, 키를 빼는
           * 것이 곧 「서버 기본을 쓴다」는 표현이다 (#892).
           *
           * 이름이 바뀌는 둘(`base_distance_nm` → `direct_distance_nm`,
           * `base_speed_kn` → `current_speed_kn`)만 여기서 옮긴다 — 나머지는
           * 서버 필드명을 그대로 쓴다.
           */
          body: JSON.stringify({
            vessel_id: request.vessel_id,
            regulation_year: request.regulation_year,
            current_speed_kn: request.base_speed_kn,
            fuel_type: request.fuel_type,
            direct_distance_nm: request.base_distance_nm,
            base_daily_foc_ton: request.base_daily_foc_ton,
            detour_distance_nm: request.detour_distance_nm,
            slow_speed_kn: request.slow_speed_kn,
            current_lat: request.current_lat,
            current_lon: request.current_lon,
            weather_model: request.weather_model,
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
         * 서버가 보낸 경고를 그대로 넘긴다 (#821).
         *
         * 종전에는 `warnings: []` 리터럴이었다. 화면의 배너 조건
         * (`ScenarioComparison.tsx`의 `response.warnings.length > 0`)이 **영구 거짓**이
         * 되어 `NON_CII_VESSEL`·`CII_APPLICABILITY_UNKNOWN`·`WEATHER_NONE_FALLBACK`·
         * `SLOW_SPEED_FLOOR`·`REFERENCE_ONLY`가 이 화면에서만 사라졌다. 같은 코드를
         * 기능① CII 예측 화면은 정상 표시한다 — 문구 맵(`voyage-cii/resultRules.ts`)은
         * 두 화면이 공유하므로 **값만 넘기면 된다.**
         *
         * 코드를 여기서 거르지 않는다. 모르는 코드는 `warningMessage()`가 **코드
         * 자체를 보여 준다** — 조용히 감추면 경고가 사라진다(`#630`의 판단).
         */
        warnings: body?.warnings ?? [],
        /*
         * 면책 문구도 서버 값을 그대로 쓴다 (#821).
         *
         * 종전에는 접두 `본 결과는 `이 붙은 **별도 문자열**이라, 서버 정본
         * (`services/voyage_cii.py`의 `DISCLAIMER`)을 고쳐도 이 화면만 옛 문구가
         * 남았다. 기능①은 이미 서버 값을 쓴다(`CiiForecastPage.tsx`).
         *
         * 값이 비면 `DisclaimerBanner`가 `PRD §6.3` 기본 문구로 대체한다 — 여기서
         * 다시 기본값을 두면 **같은 문구가 두 곳**이 되어 또 갈린다.
         */
        disclaimer: body?.disclaimer ?? '',
      }
    },
  }
}
