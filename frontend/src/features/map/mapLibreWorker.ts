/**
 * MapLibre 워커의 자리를 **빌드가 내보낸 자산**으로 고정한다 (`#1909`).
 *
 * ## 무엇이 깨져 있었나
 *
 * maplibre는 타일 파싱을 Web Worker에서 한다. v6는 그 워커의 주소를 **런타임에
 * 조립한다** — 번들에 들어간 코드가 이렇게 생겼다.
 *
 * ```js
 * let e = import.meta.url
 * let t = e.endsWith('-dev.mjs') ? 'maplibre-gl-worker-dev.mjs' : 'maplibre-gl-worker.mjs'
 * return new URL(`./${t}`, e).href
 * ```
 *
 * 파일 이름이 **삼항 연산으로 정해지므로** 번들러가 정적으로 읽지 못한다. 그래서
 * `new URL('./…', import.meta.url)`을 자산으로 내보내는 Vite의 처리가 걸리지 않고,
 * **`dist/assets/maplibre-gl-worker.mjs`가 만들어지지 않는다.**
 *
 * 없는 자산을 부르면 **SPA 폴백이 `index.html`을 `200`으로 돌려준다**(`_redirects`).
 * 워커는 HTML을 자바스크립트로 읽다 죽는데, `#1144`가 적은 그대로 **조용하다** —
 * maplibre는 `error` 이벤트를 내지 않고, 지도는 스타일 배경색만 칠한 **회색
 * 사각형**으로 남으며 `load`가 오지 않아 마커도 항로도 붙지 않는다. 타일 요청은
 * **한 건도 나가지 않는다.**
 *
 * 개발 서버에서는 뜬다 — Vite가 패키지의 실제 파일을 그대로 서빙하기 때문이다
 * (`vite.config.ts`의 `optimizeDeps.exclude`가 그 경로를 지킨다 · `#1144`). 그래서
 * `e2e/map-smoke.spec.ts`도 통과했다. **개발과 배포가 갈리는 자리였다.**
 *
 * ## 왜 파일을 복사해 두지 않는가
 *
 * `dist/assets/`에 원본 이름 그대로 복사하면 런타임이 조립한 주소가 맞는다. 그러나
 * `public/_headers`가 `/assets/*`에 **1년 immutable 캐시**를 건다 — 이름에 해시가 없는
 * 그 두 파일(`-worker.mjs`·`-shared.mjs`)은 maplibre를 올려도 **낡은 사본이 1년 동안
 * 남는다.** 캐시 규칙과 어긋나는 파일을 그 디렉터리에 두지 않는다.
 *
 * `?worker&url`은 Vite가 워커를 **의존성까지 묶어 해시 붙은 자산 하나로** 내보내고 그
 * 주소를 준다. 이름이 내용에 따라 바뀌므로 immutable 캐시가 그대로 맞고,
 * `maplibre-gl-shared.mjs`를 따로 둘 필요도 없다.
 */

import { setWorkerUrl } from 'maplibre-gl'
// Vite가 이 워커를 번들해 자산으로 내보내고, 그 주소를 문자열로 준다.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

let applied = false

/**
 * 지도를 만들기 **전에** 부른다. 두 번째부터는 아무 일도 하지 않는다 —
 * `setWorkerUrl`은 전역 설정이고, 워커 풀이 이미 떠 있으면 바꿔도 소용이 없다.
 */
export function ensureMapLibreWorker(): void {
  if (applied) return
  applied = true
  setWorkerUrl(workerUrl)
}
