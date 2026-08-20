import { API_BASE_URL_ENV_KEY, API_KEY_ENV_KEY } from '../voyage-cii/providerSelection'
import { createApiVesselManagementProvider } from './apiProvider'
import type { VesselManagementProvider } from './provider'

/**
 * 선박 관리 provider 생성 (#510 · #542).
 *
 * ## 종전에는 데모 경계가 있었다
 *
 * 데모 모드에서는 목록·수정·삭제가 전부 `DEMO_UNAVAILABLE`로 실패했다. 목록은 읽기라
 * 고정표로 흉내 낼 수 있었으나 그렇게 하지 않았다 — 고정표에는 선박이 1척뿐이고 `id`가
 * 서버 UUID와 달라, 그 목록에서 수정·삭제를 누르면 **실 서버에 없는 id로 요청**이
 * 나가기 때문이다.
 *
 * `#542`가 데모 모드를 폐기해 그 경계가 필요 없어졌다.
 */
export function createVesselManagementProvider(
  env: ImportMetaEnv = import.meta.env,
): VesselManagementProvider {
  return createApiVesselManagementProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}
