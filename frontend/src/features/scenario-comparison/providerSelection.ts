import { isEnabled, USE_API_ENV_KEY } from '../voyage-cii/providerSelection'
import { createApiScenarioProvider } from './apiProvider'
import { createDemoScenarioProvider } from './demoProvider'
import type { ScenarioComparisonProvider } from './provider'

/**
 * 기능② demo ↔ 실 API 전환 (#139).
 *
 * 기능①의 `providerSelection`과 **같은 스위치**(`VITE_USE_API`)를 공유한다. 두 기능이
 * 별도 스위치를 가지면 한쪽만 실 API인 상태가 만들어지고, 화면 간 값이 어긋나도
 * 원인을 찾기 어렵다.
 *
 * 기본값이 demo인 이유도 같다 — 실 API를 기본으로 두면 백엔드가 없는 환경에서
 * 화면이 **오류로 시작**하고, 그 상태는 「아직 안 만들었다」와 「연결이 끊겼다」를
 * 구분하지 못한다.
 */
export function selectScenarioProvider(
  env: ImportMetaEnv = import.meta.env,
): ScenarioComparisonProvider {
  return isEnabled(env[USE_API_ENV_KEY])
    ? createApiScenarioProvider()
    : createDemoScenarioProvider()
}
