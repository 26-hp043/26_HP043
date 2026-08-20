import { createApiProvider } from './apiProvider'
import type { VoyageCiiProvider } from './provider'

/**
 * 기능① provider 생성 (#138 · #542).
 *
 * ## 종전에는 스위치였다
 *
 * `VITE_USE_API`로 demo provider와 실 API provider를 갈랐다. 백엔드가 없던 시기에
 * 화면을 먼저 만들기 위한 장치였고 8/8 시연도 그 경로로 했다.
 *
 * **`#542`가 데모 모드를 폐기했다.** 두 경로가 함께 남아 경계가 새는 사고가 네 번
 * 반복됐고(`#511` · `#526` · `#534` · `#528`), 데모 경로가 12개 기능 중 3개만 덮어
 * 「백엔드 없이 화면 검토」라는 원래 목적도 이미 성립하지 않았다.
 *
 * ## 파일을 남기는 이유
 *
 * 실 API provider도 이 파일이 만든다. 화면은 이 함수만 부르고 **어떻게 만들어지는지
 * 알지 않는다** — `#134`가 provider 경계를 그은 이유가 그것이며, 그 경계는 데모
 * 폐기와 무관하게 유효하다.
 *
 * ## 백엔드가 없으면
 *
 * 화면이 오류로 시작한다. 종전 주석이 *「그 상태는 "아직 안 만들었다"와 "연결이
 * 끊겼다"를 구분하지 못한다」*고 적어 이것을 demo 기본값의 근거로 삼았으나,
 * 실제 기본값은 `#528` 이후 이미 실 API였다. 구분은 **오류 문구**로 하는 것이 맞고
 * provider 선택으로 할 일이 아니다.
 */

/** base URL을 덮어쓰는 환경변수. 미설정 시 `apiProvider`의 기본값(상대 경로)을 쓴다. */
export const API_BASE_URL_ENV_KEY = 'VITE_API_BASE_URL'

/** `#104` API Key. 적용 전에는 비어 있다. */
export const API_KEY_ENV_KEY = 'VITE_API_KEY'

/** 환경에 맞는 provider를 만든다. */
export function createVoyageCiiProvider(
  env: ImportMetaEnv = import.meta.env,
): VoyageCiiProvider {
  return createApiProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}
