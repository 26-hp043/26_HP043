import { API_BASE_URL_ENV_KEY, API_KEY_ENV_KEY } from '../voyage-cii/providerSelection'
import { createApiVesselRegistrationProvider } from './apiProvider'
import type { VesselRegistrationProvider } from './provider'

/**
 * 등록 provider 생성 (#441 · #542).
 *
 * ## 종전에는 데모 경계가 있었다
 *
 * 데모 모드에서 등록은 **항상 실패**했다. 다른 기능의 데모 provider는 읽기(계산·조회)라
 * 고정표로 대신할 수 있지만 등록은 쓰기이고, 성공을 흉내 내면 대시보드에 그 배가 없고
 * 새로 고치면 사라지는 상태가 만들어지기 때문이었다.
 *
 * `#542`가 데모 모드를 폐기해 그 경계가 필요 없어졌다. **판단 자체는 옳았고 폐기의
 * 근거이기도 하다** — 데모가 덮지 못하는 기능이 늘어난 것이 이번 결정의 배경이다.
 */
export function createVesselRegistrationProvider(
  env: ImportMetaEnv = import.meta.env,
): VesselRegistrationProvider {
  return createApiVesselRegistrationProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}
