import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from './apiProvider'
import { selectableVessels } from './formRules'
import { API_BASE_URL_ENV_KEY, shouldUseApi } from './providerSelection'

/**
 * 선박 선택지의 데이터 경계 (#236).
 *
 * ## 왜 별도 provider인가
 *
 * `#206`이 계산 호출을 실 API로 바꿨지만 **선택지 소스는 바꾸지 않아**,
 * `VITE_USE_API=true`에서도 `formRules.ts` → `referenceTable.ts`의 고정표를 읽는다.
 * 018 seed는 선박 3척을 넣는데 고정표에는 1척뿐이라 **2척이 화면에서 도달 불가능**하고,
 * `#51`로 만든 `GET /api/v1/vessels`는 소비처 없이 방치된다.
 *
 * `VoyageCiiProvider`에 메서드를 더하지 않고 별도 인터페이스로 둔 이유는 두 가지다.
 *
 * 1. **관심사가 다르다.** `VoyageCiiProvider.estimate()`는 계산이고 이쪽은 목록 조회다.
 *    한 인터페이스에 묶으면 demo·api 양쪽 구현이 쓰지도 않는 메서드를 갖는다.
 * 2. **재사용처가 기능① 밖에 있다.** 대시보드(`#351`)와 선박 상세(`#356`)도 선박
 *    목록이 필요하다. 기능① provider에 넣으면 그 화면들이 계산 provider를 끌고 온다.
 *
 * ## 화면 타입을 좁게 잡는다
 *
 * `DemoVessel`은 `transportCapacity`·`referenceCapacityRule` 같은 **고정표 전용 필드**를
 *갖는데, 이 값들은 `cii_reference_line`에서 오는 것이라 `GET /api/v1/vessels` 응답에
 * 없다. 셀렉트가 실제로 쓰는 것은 `id`와 표시 이름뿐이므로 그 둘만 담는 타입을 둔다 —
 * 없는 필드를 채우려고 서버 응답을 가공하면 화면이 계산 규칙을 다시 갖게 된다.
 */
export interface VesselOption {
  id: string
  displayName: string
  shipType: string
}

/** 선박 목록 조회의 데이터 경계. 화면은 출처를 알지 않는다 (`#134`). */
export interface VesselCatalogProvider {
  listVessels(): Promise<VesselOption[]>
}

/**
 * demo 구현 — 기존 `selectableVessels()`를 그대로 감싼다.
 *
 * **8/8 데모 경로가 바뀌면 안 된다.** 백엔드 없이 화면이 도는 구조에서는 지금의
 * 고정표가 옳고, 계산 가능한 조합만 선택지가 되어야 한다는 `#135` 설계 요구도
 * 그 필터에 들어 있다.
 */
export function createDemoVesselCatalog(): VesselCatalogProvider {
  return {
    async listVessels() {
      return selectableVessels().map((v) => ({
        id: v.id,
        displayName: v.displayName,
        shipType: v.shipType,
      }))
    },
  }
}

/** `GET /api/v1/vessels` 응답 중 선택지에 필요한 부분. */
interface VesselListItem {
  id?: unknown
  name?: unknown
  ship_type?: unknown
}

/**
 * 실 API 구현 — `GET /api/v1/vessels` (`API_SPEC §2.1`).
 *
 * 표시 이름은 서버의 `name`을 그대로 쓴다. 고정표의 `displayName`처럼 제원을 덧붙이지
 * 않는다 — 덧붙이려면 화면이 DWT/GT 중 무엇이 축인지 판단해야 하고, 그 판단은
 * `cii_reference_line.capacity_rule` 소관이라 여기서 흉내 내면 두 곳에 규칙이 생긴다.
 *
 * 페이지네이션은 따라가지 않는다. `API_SPEC §1.5` 기본 limit 안에서 선택지가 끝나는
 * 규모이며, 넘어가면 셀렉트가 아니라 검색 UI가 필요한 별개 문제다.
 */
export function createApiVesselCatalog(baseUrl?: string): VesselCatalogProvider {
  const base = baseUrl || DEFAULT_API_BASE_URL
  return {
    async listVessels() {
      let response: Response
      try {
        response = await fetch(`${base}/vessels`, {
          method: 'GET',
          credentials: 'include',
          headers: csrfHeaders(),
        })
      } catch (cause) {
        throw new VesselCatalogError('서버에 연결하지 못했습니다.', { cause })
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new VesselCatalogError('로그인이 필요합니다.')
      }
      if (!response.ok) {
        throw new VesselCatalogError('선박 목록을 불러오지 못했습니다.')
      }

      let body: { data?: unknown }
      try {
        body = (await response.json()) as { data?: unknown }
      } catch (cause) {
        throw new VesselCatalogError('선박 목록 응답을 해석하지 못했습니다.', { cause })
      }

      const rows = Array.isArray(body.data) ? (body.data as VesselListItem[]) : []
      return rows
        .filter((row) => typeof row.id === 'string' && typeof row.name === 'string')
        .map((row) => ({
          id: row.id as string,
          displayName: row.name as string,
          shipType: typeof row.ship_type === 'string' ? row.ship_type : '',
        }))
    },
  }
}

/**
 * 선택지 조회 실패.
 *
 * `VoyageCiiError`를 재사용하지 않는다 — 그쪽 코드 집합(`UNSUPPORTED_VESSEL` 등)은
 * **계산 요청**의 실패를 가리키며, 목록을 못 불러온 것과 성격이 다르다. 섞으면
 * 화면이 「고를 수 없는 선박을 골랐다」와 「목록 자체가 없다」를 구분하지 못한다.
 */
export class VesselCatalogError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'VesselCatalogError'
  }
}

/**
 * demo ↔ 실 API 전환. 판단 기준은 계산 provider와 **같은 환경변수**다 (`#138`).
 *
 * 기준이 갈리면 계산은 서버로 가는데 선택지는 고정표에서 오는, 지금 고치려는
 * 상태가 다시 만들어진다.
 */
export function createVesselCatalog(
  env: ImportMetaEnv = import.meta.env,
): VesselCatalogProvider {
  if (!shouldUseApi(env)) return createDemoVesselCatalog()
  return createApiVesselCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}
