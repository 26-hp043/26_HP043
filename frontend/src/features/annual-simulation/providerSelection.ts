import { API_BASE_URL_ENV_KEY, API_KEY_ENV_KEY } from '../voyage-cii/providerSelection'
import { createApiAnnualSimulationProvider } from './apiProvider'
import type { AnnualSimulationProvider } from './types'

/**
 * 기능③ provider 생성 (#442 · #542).
 *
 * 종전에는 기능①·②와 같은 스위치(`VITE_USE_API`)로 demo ↔ 실 API를 갈랐다. 기능별
 * 스위치를 두면 「기능①은 실 API, 기능③은 demo」 같은 섞인 상태가 생기고, 화면에서
 * 본 값이 어느 쪽에서 온 것인지 알 수 없기 때문이었다.
 *
 * `#542`가 데모 모드를 폐기해 갈래가 하나만 남았다.
 */
export function createAnnualSimulationProvider(
  env: ImportMetaEnv = import.meta.env,
): AnnualSimulationProvider {
  return createApiAnnualSimulationProvider({
    baseUrl: env[API_BASE_URL_ENV_KEY] as string | undefined,
    apiKey: env[API_KEY_ENV_KEY] as string | undefined,
  })
}
