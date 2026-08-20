// `vite`가 아니라 `vitest/config`에서 가져온다 — 아래 `test` 블록의 타입이 거기 있다.
// `vite`의 `defineConfig`를 쓰면 `test`가 「알 수 없는 속성」으로 tsc가 막는다 (#557).
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * 저장소가 **Windows 파일시스템 위에 있는 WSL 환경**인지.
 *
 * WSL2에서 `/mnt/c/...`에 있는 파일을 고치면 **inotify 이벤트가 WSL 쪽으로 전달되지
 * 않는다.** Vite의 파일 감시가 조용히 아무것도 감지하지 못하고, 개발 서버는 기동
 * 시점의 코드를 계속 서빙한다.
 *
 * **실패가 눈에 띄지 않는 것이 문제다** — 서버는 살아 있고 `HTTP 200`을 내며 화면도
 * 정상으로 보인다. 다만 내용이 옛것이다. 2026-08-07에 `#135`~`#157`이 전부 머지된
 * 뒤에도 화면이 `#133`의 「준비 중」이던 사고가 이 원인이었다.
 *
 * 폴링은 CPU를 계속 쓰므로 **필요한 환경에서만 켠다.** 리눅스이면서 작업 디렉터리가
 * `/mnt/`로 시작하는 경우가 정확히 그 조건이다 — 네이티브 리눅스·macOS·Windows나
 * WSL 홈(`~/`)에 둔 경우에는 켜지지 않는다.
 *
 * CI는 개발 서버를 띄우지 않으므로 영향이 없다.
 */
const isRepoOnWindowsFilesystem =
  process.platform === 'linux' && process.cwd().startsWith('/mnt/')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  /*
   * 테스트 환경 (#557).
   *
   * **전역 environment를 `jsdom`으로 바꾸지 않는다.** 이 저장소의 테스트 42개 파일은
   * 순수 함수와 provider를 보는 것이라 DOM이 필요 없다. 전역으로 켜면 그 전부가
   * 매번 DOM을 세우느라 느려지고, **DOM에 기대지 않는다는 성질도 흐려진다** —
   * 규칙을 순수 함수로 뽑아 둔 구조(`formRules.ts` 머리주석)가 그 성질에 기대고 있다.
   *
   * 컴포넌트 테스트는 파일 머리에 `// @vitest-environment jsdom`을 적어 **그 파일만**
   * DOM 환경으로 돈다. 어느 파일이 DOM을 쓰는지 파일을 열면 바로 보인다.
   */
  test: {
    environment: 'node',
    globals: false,
  },
  server: {
    ...(isRepoOnWindowsFilesystem
      ? {
          watch: {
            usePolling: true,
            /** 저장 후 반영까지의 지연. 낮추면 CPU를 더 쓴다. */
            interval: 300,
          },
        }
      : {}),
    /*
     * 백엔드 프록시 (#138).
     *
     * 개발 중 프론트엔드(5173)와 백엔드(8000)가 다른 포트로 뜬다. 브라우저가 이를
     * 다른 출처로 보아 요청을 막으므로(CORS) 둘 중 하나를 해야 한다 —
     * **⑴ 개발 서버 프록시** 또는 ⑵ 백엔드에 CORS 허용 오리진 추가.
     *
     * ⑴을 택했다. 이유:
     *
     * - **백엔드에 개발 전용 설정을 넣지 않는다.** CORS 허용 오리진은 프로덕션에서
     *   위험한 값이고, 개발용 오리진이 배포 설정에 섞이면 지우는 것을 잊는다.
     * - **프론트엔드가 상대 경로(`/api/v1`)를 쓸 수 있다.** 절대 URL을 쓰면 배포
     *   환경마다 base URL을 바꿔야 하는데, 같은 도메인에 서빙되는 프로덕션에서는
     *   상대 경로가 그대로 맞는다.
     * - 브라우저 입장에서 **같은 출처**가 되므로 preflight 자체가 없다.
     *
     * 대상 주소는 `VITE_API_PROXY_TARGET`으로 바꿀 수 있다(도커 컴포즈에서 서비스명
     * 사용 등). 미설정 시 로컬 기본값을 쓴다.
     */
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
