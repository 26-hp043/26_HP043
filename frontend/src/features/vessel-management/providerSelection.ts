import {
  API_BASE_URL_ENV_KEY,
  API_KEY_ENV_KEY,
  shouldUseApi,
} from '../voyage-cii/providerSelection'
import { createApiVesselManagementProvider } from './apiProvider'
import { VesselManagementError, type VesselManagementProvider } from './provider'

/**
 * 선박 관리 provider 선택 (#510).
 *
 * 판단 기준은 다른 기능과 **같은 환경변수**(`VITE_USE_API`)다. 기준이 갈리면 화면마다
 * 다른 세계를 보게 된다(`#236`이 고친 것이 정확히 그 상태였다).
 *
 * ## 데모에서는 목록도 보이지 않는다
 *
 * 등록(`vessel-registration/providerSelection.ts`)은 「쓰기라서 흉내 낼 수 없다」였다.
 * 관리 화면은 목록이 **읽기**라 고정표로 흉내 낼 수는 있는데, 그렇게 하지 않는다 —
 *
 * - 목록만 보이고 수정·삭제가 전부 실패하면 **어디까지가 데모인지 화면에서 알 수 없다.**
 *   버튼을 눌러 봐야 알게 되는 상태는 「없다」보다 나쁘다.
 * - 고정표(`referenceTable.ts`)에는 선박이 1척뿐이고 `id`가 서버 UUID와 다르다.
 *   그 목록에서 수정·삭제를 누르면 **실 서버에 없는 id로 요청**이 나간다.
 * - 이 화면의 목적은 「지금 내 배가 어떤 상태인가」다. 고정표는 그 질문에 답하지 못한다.
 */

/** 데모 모드 안내 문구. 화면 배너와 조작 실패가 같은 말을 쓴다. */
export const DEMO_UNAVAILABLE_MESSAGE =
  '데모 모드에서는 선박 관리를 사용할 수 없습니다. 목록·수정·삭제 모두 서버의 실제 데이터를 다루므로 백엔드 연결이 필요합니다.'

/**
 * 데모 모드의 관리 경계 — 항상 실패한다.
 *
 * provider를 아예 두지 않는 방법(화면이 `null`을 다루기)을 택하지 않았다. 화면이
 * 「provider가 없는 경우」를 갖게 되면 그 분기가 실 API 경로에도 남는다
 * (`vessel-registration`과 같은 판단).
 */
export function createUnavailableVesselManagementProvider(): VesselManagementProvider {
  const fail = () => {
    throw new VesselManagementError('DEMO_UNAVAILABLE', DEMO_UNAVAILABLE_MESSAGE)
  }
  return {
    async list() {
      return fail()
    },
    async update() {
      return fail()
    },
    async remove() {
      return fail()
    },
  }
}

export function createVesselManagementProvider(
  env: ImportMetaEnv = import.meta.env,
): VesselManagementProvider {
  if (!shouldUseApi(env)) return createUnavailableVesselManagementProvider()
  return createApiVesselManagementProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}

/** 화면이 「지금 관리가 가능한가」를 묻는 통로. 배너 표시·버튼 상태에 쓴다. */
export function isManagementAvailable(env: ImportMetaEnv = import.meta.env): boolean {
  return shouldUseApi(env)
}
