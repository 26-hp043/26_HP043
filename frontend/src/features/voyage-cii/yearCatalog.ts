import { createApiParametersProvider, ParametersError } from '../parameters/apiProvider'
import { DEFAULT_API_BASE_URL } from './apiProvider'
import { selectableYears } from './formRules'
import { API_BASE_URL_ENV_KEY, shouldUseApi } from './providerSelection'

/**
 * 규제연도 선택지의 데이터 경계 (#534).
 *
 * ## 왜 이제 만드는가
 *
 * `#236`이 「실API 모드에서도 선박·연도·연료 선택지가 프론트엔드 고정표에서 온다」를
 * 고치면서 **선박 축만 옮기고 연도 축은 유예했다.** 그 이슈 체크리스트의 문구가
 * 조건까지 남겨 두었다.
 *
 * > `regulation_year` 선택지의 출처를 정한다. 현재 서버에 규정연도 목록 엔드포인트가
 * > 없다 — 없다면 이 이슈에서 만들지 말고 후속 이슈로 분리하고, 그때까지 연도는
 * > 고정표를 유지한다
 *
 * 그 엔드포인트가 `#444`로 들어왔다(`GET /parameters/regulation-years`,
 * `API_SPEC §7.1`). 유예 조건이 풀렸으므로 남은 절반을 여기서 옮긴다.
 *
 * ## 무엇이 깨져 있었나
 *
 * `selectableYears()`는 `FIXED_PARAMETERS`를 읽는데 그 표에는 행이 하나뿐이고
 * `vesselId`가 `…0001`(샘플 벌크선)이다. `demo_seed`는 선박 4척을 넣으므로,
 * 실 API 모드에서 나머지 3척을 고르면 연도 목록이 빈 배열이 되어 **계산 자체가
 * 불가능**했다. 선종 문제가 아니라 **선박 UUID 일치 문제**이므로, 사용자가 새로
 * 등록하는 선박도 예외 없이 같은 상태가 된다.
 *
 * ## 선박 축과 같은 스위치를 쓴다
 *
 * `vesselCatalog.ts`가 적어 둔 이유를 그대로 따른다 — 기준이 갈리면 계산은 서버로
 * 가는데 선택지는 고정표에서 오는, 지금 고치려는 상태가 다시 만들어진다.
 */

/** 규제연도 선택지 조회의 데이터 경계. 화면은 출처를 알지 않는다 (`#134`). */
export interface YearCatalogProvider {
  /**
   * 해당 선박이 고를 수 있는 규제연도. 오름차순.
   *
   * **실 API 구현은 `vesselId`를 쓰지 않는다.** Z계수는 전 선종 공통이라 선박마다
   * 목록이 갈리지 않기 때문이다(`parameters/apiProvider.ts` 주석 참조). 인자를
   * 남겨 둔 것은 demo 구현이 고정표를 `(vesselId, year)` 키로 들고 있어서이며,
   * 두 구현이 같은 서명을 갖도록 맞춘 것이다.
   */
  listYears(vesselId: string): Promise<number[]>
}

/**
 * demo 구현 — 기존 `selectableYears()`를 그대로 감싼다.
 *
 * **8/8 데모 경로가 바뀌면 안 된다.** 백엔드 없이 화면이 도는 구조에서는 고정표가
 * 옳고, 계산 가능한 조합만 선택지가 되어야 한다는 `#135` 설계 요구도 그 표에 있다.
 * 데모 모드 자체의 존치 여부는 `#542`에서 따로 다룬다.
 */
export function createDemoYearCatalog(): YearCatalogProvider {
  return {
    async listYears(vesselId: string) {
      return selectableYears(vesselId)
    },
  }
}

/**
 * 실 API 구현 — `GET /api/v1/parameters/regulation-years` (`API_SPEC §7.1`).
 *
 * 조회는 `features/parameters`의 공용 provider에 위임한다. 여기서 `fetch`를 다시
 * 쓰면 같은 엔드포인트를 부르는 코드가 두 벌이 되고, 그것이 `#444`가 없앤 상태다.
 *
 * ## 한 번만 받는다
 *
 * 화면은 **선박을 바꿀 때마다** 이 함수를 부른다 — demo 구현이 선박별로 다른 답을
 * 내기 때문이다. 실 API 쪽 답은 선박과 무관하게 같으므로, 그대로 두면 선박을 고를
 * 때마다 같은 GET이 반복된다. 성공한 조회 하나를 붙들어 재사용한다.
 *
 * **실패는 붙들지 않는다.** 실패까지 캐시하면 일시적인 네트워크 오류가 새로고침
 * 전까지 영구 실패로 굳는다.
 */
export function createApiYearCatalog(baseUrl?: string): YearCatalogProvider {
  const parameters = createApiParametersProvider(globalThis.fetch, baseUrl || DEFAULT_API_BASE_URL)
  let inFlight: Promise<number[]> | null = null

  return {
    async listYears() {
      if (inFlight === null) {
        inFlight = parameters.listRegulationYears().catch((cause) => {
          inFlight = null
          if (cause instanceof ParametersError) {
            throw new YearCatalogError(cause.message, { cause })
          }
          throw new YearCatalogError('규제연도 목록을 불러오지 못했습니다.', { cause })
        })
      }
      return inFlight
    },
  }
}

/**
 * 선택지 조회 실패.
 *
 * `VoyageCiiError`를 재사용하지 않는다 — `vesselCatalog.ts`가 적은 이유와 같다.
 * 계산 요청의 실패와 목록을 못 불러온 것은 성격이 다르고, 섞으면 화면이
 * 「고를 수 없는 연도를 골랐다」와 「목록 자체가 없다」를 구분하지 못한다.
 */
export class YearCatalogError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'YearCatalogError'
  }
}

/** demo ↔ 실 API 전환. 판단 기준은 계산·선박 provider와 **같은 환경변수**다 (`#138`). */
export function createYearCatalog(env: ImportMetaEnv = import.meta.env): YearCatalogProvider {
  if (!shouldUseApi(env)) return createDemoYearCatalog()
  return createApiYearCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}
