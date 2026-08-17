import {
  API_BASE_URL_ENV_KEY,
  API_KEY_ENV_KEY,
  shouldUseApi,
} from '../voyage-cii/providerSelection'
import { createApiAnnualSimulationProvider } from './apiProvider'
import { createDemoAnnualProvider } from './demoProvider'
import type { AnnualSimulationProvider } from './types'

/**
 * demo provider ↔ 실 API provider 전환 (#442).
 *
 * ## 기능①과 **같은 스위치**를 쓴다
 *
 * `VITE_USE_API` 하나로 화면 전체가 함께 전환된다. 기능별로 스위치를 두면 「기능①은 실
 * API, 기능③은 demo」 같은 **섞인 상태**가 생기고, 그 화면에서 본 값이 어느 쪽에서 온
 * 것인지 알 수 없다.
 *
 * `#139`(기능②)도 같은 판단으로 기능①의 스위치를 공유한다.
 *
 * ## 기본값이 demo인 이유
 *
 * 실 API를 기본으로 두면 백엔드가 없는 환경에서 화면이 **오류로 시작**한다. 그 상태는
 * 「아직 안 만들었다」와 「연결이 끊겼다」를 구분하지 못한다.
 */
export function createAnnualSimulationProvider(
  env: ImportMetaEnv = import.meta.env,
): AnnualSimulationProvider {
  if (!shouldUseApi(env)) return createDemoAnnualProvider()
  return createApiAnnualSimulationProvider({
    baseUrl: env[API_BASE_URL_ENV_KEY] as string | undefined,
    apiKey: env[API_KEY_ENV_KEY] as string | undefined,
  })
}
