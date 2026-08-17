import {
  API_BASE_URL_ENV_KEY,
  API_KEY_ENV_KEY,
  shouldUseApi,
} from '../voyage-cii/providerSelection'
import { createApiVesselRegistrationProvider } from './apiProvider'
import { VesselRegistrationError, type VesselRegistrationProvider } from './provider'

/**
 * 등록 provider 선택 (#441).
 *
 * 판단 기준은 다른 기능과 **같은 환경변수**(`VITE_USE_API`)다. 기준이 갈리면 화면마다
 * 다른 세계를 보게 된다(`#236`이 고친 것이 정확히 그 상태였다).
 *
 * ## 데모에 「가짜 등록 성공」을 두지 않는다
 *
 * 다른 기능의 데모 provider는 **읽기**(계산·조회)라 고정표로 대신할 수 있다. 등록은
 * **쓰기**다. 성공을 흉내 내면 그 다음 화면에서 문제가 드러난다 —
 *
 * - 대시보드에 그 배가 없다. 사용자는 등록이 사라졌다고 본다
 * - 같은 배를 다시 등록한다. 실 서버에서는 409가 나야 할 조작이 데모에서는 계속 성공한다
 * - **화면을 새로 고치면 없어진다.** 어디까지가 데모인지 사용자가 알 수 없다
 *
 * 그래서 데모에서는 등록이 **불가능하다는 사실을 명시**한다. `#419`~`#449`에서 반복해
 * 확인한 것과 같은 원칙이다 — 계산할 수 없을 때 그럴듯한 값을 만들지 않고 그 사실을
 * 값으로 만든다.
 */

/** 데모 모드 안내 문구. 화면 상단 배너와 제출 시 오류가 같은 말을 쓴다. */
export const DEMO_UNAVAILABLE_MESSAGE =
  '데모 모드에서는 선박을 등록할 수 없습니다. 등록은 서버에 저장되는 조작이므로 백엔드 연결이 필요합니다.'

/**
 * 데모 모드의 등록 경계 — 항상 실패한다.
 *
 * provider를 아예 두지 않는 방법(화면이 `null`을 다루기)을 택하지 않았다. 화면이
 * 「provider가 없는 경우」를 갖게 되면 그 분기가 실 API 경로에도 남는다.
 */
export function createUnavailableVesselRegistrationProvider(): VesselRegistrationProvider {
  return {
    async register() {
      throw new VesselRegistrationError('DEMO_UNAVAILABLE', DEMO_UNAVAILABLE_MESSAGE)
    },
  }
}

export function createVesselRegistrationProvider(
  env: ImportMetaEnv = import.meta.env,
): VesselRegistrationProvider {
  if (!shouldUseApi(env)) return createUnavailableVesselRegistrationProvider()
  return createApiVesselRegistrationProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}

/** 화면이 「지금 등록이 가능한가」를 묻는 통로. 배너 표시·제출 버튼 상태에 쓴다. */
export function isRegistrationAvailable(env: ImportMetaEnv = import.meta.env): boolean {
  return shouldUseApi(env)
}
