import { defineConfig } from 'vite'
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
  server: isRepoOnWindowsFilesystem
    ? {
        watch: {
          usePolling: true,
          /** 저장 후 반영까지의 지연. 낮추면 CPU를 더 쓴다. */
          interval: 300,
        },
      }
    : undefined,
})
