import { createApiScenarioProvider } from './apiProvider'
import type { ScenarioComparisonProvider } from './provider'

/**
 * 기능② provider 생성 (#139 · #542).
 *
 * 종전에는 기능①과 **같은 스위치**(`VITE_USE_API`)를 공유해 demo ↔ 실 API를 갈랐다.
 * 두 기능이 별도 스위치를 가지면 한쪽만 실 API인 상태가 만들어지기 때문이었다.
 *
 * `#542`가 데모 모드를 폐기해 갈래가 하나만 남았다. 스위치를 공유하던 이유는
 * 그대로 유효하나, 공유할 스위치 자체가 없어졌다.
 */
export function selectScenarioProvider(
  _env: ImportMetaEnv = import.meta.env,
): ScenarioComparisonProvider {
  return createApiScenarioProvider()
}
