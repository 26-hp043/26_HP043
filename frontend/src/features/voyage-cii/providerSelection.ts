import { createApiProvider } from './apiProvider'
import { createDemoProvider } from './demoProvider'
import type { VoyageCiiProvider } from './provider'

/**
 * demo provider ↔ 실 API provider 전환 (#138).
 *
 * ## 왜 스위치가 필요한가
 *
 * 백엔드가 없어도 화면이 돌아야 한다. `#135`~`#157`이 그 전제로 만들어졌고, 8/8 데모도
 * demo provider로 수행했다. 실 API가 붙은 뒤에도 **백엔드를 띄우지 않고 화면만 보는
 * 상황**(디자인 검토·프론트엔드 리팩터링)이 남는다.
 *
 * ## 기본값이 demo인 이유
 *
 * 실 API를 기본으로 두면 백엔드가 없는 환경에서 화면이 **오류로 시작**한다. 그 상태는
 * 「아직 안 만들었다」와 「연결이 끊겼다」를 구분하지 못한다. **명시적으로 켜는 쪽**이
 * 안전하다.
 *
 * ```
 * frontend/.env.local
 *   VITE_USE_API=true
 * ```
 *
 * ## 값 해석을 느슨하게 하지 않는다
 *
 * `"true"`만 참으로 본다. `.env`의 값은 전부 문자열이라 `Boolean("false")`가 `true`가
 * 되는 함정이 있다 — 그걸 피하려고 문자열을 직접 비교한다.
 */

/** 실 API를 쓰도록 켜는 환경변수 이름. */
export const USE_API_ENV_KEY = 'VITE_USE_API'

/** base URL을 덮어쓰는 환경변수. 미설정 시 `apiProvider`의 기본값(상대 경로)을 쓴다. */
export const API_BASE_URL_ENV_KEY = 'VITE_API_BASE_URL'

/** `#104` API Key. 적용 전에는 비어 있다. */
export const API_KEY_ENV_KEY = 'VITE_API_KEY'

/** 문자열 `"true"`만 참으로 본다. 위 docstring 참조. */
export function isEnabled(raw: string | undefined): boolean {
  return raw === 'true'
}

/**
 * 현재 환경이 실 API를 쓰는지.
 *
 * `import.meta.env`를 직접 읽는 곳을 이 함수 하나로 좁힌다 — 여러 곳에서 읽으면
 * 테스트가 환경을 바꿔 가며 확인할 수 없다.
 */
export function shouldUseApi(env: ImportMetaEnv = import.meta.env): boolean {
  return isEnabled(env[USE_API_ENV_KEY] as string | undefined)
}

/**
 * 환경에 맞는 provider를 만든다.
 *
 * 화면은 이 함수만 부르고 **어느 쪽이 선택됐는지 알지 않는다.**
 */
export function createVoyageCiiProvider(
  env: ImportMetaEnv = import.meta.env,
): VoyageCiiProvider {
  if (!shouldUseApi(env)) return createDemoProvider()
  return createApiProvider({
    baseUrl: (env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined,
    apiKey: (env[API_KEY_ENV_KEY] as string | undefined) || undefined,
  })
}
