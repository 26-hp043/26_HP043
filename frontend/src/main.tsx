import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './styles/global.css'
import './styles/card.css'
import { ErrorBoundary, ErrorScreen } from './components/ErrorBoundary'
import App from './App.tsx'

/**
 * 루트 에러 경계 (`#823`).
 *
 * **React 19는 렌더 예외에서 루트를 언마운트한다** — 경계가 없으면 `#root`가 비어
 * 완전 백지가 되고, 새로고침해도 같은 지점에서 다시 던져 복구되지 않는다. 사용자가
 * 스스로 빠져나올 방법이 URL 직접 입력뿐이다.
 *
 * ## 왜 `<App/>` **밖**인가
 *
 * `App`이 `BrowserRouter`를 소유한다. 라우터 자체나 셸(`AppShell`)이 던지면
 * 화면 단위 경계(`AppShell`의 `<Outlet>` 주위)는 이미 죽은 뒤다. 이 경계는
 * **그 바깥**을 받는다.
 *
 * ## 왜 `<Link>`가 아니라 `window.location`인가
 *
 * 여기서 잡히는 예외는 **라우터가 살아 있지 않을 수 있다.** `Link`는 라우터 컨텍스트를
 * 요구하므로 오류 화면 자체가 다시 던진다 — 그러면 경계가 무의미해진다.
 * `window.location.assign`은 컨텍스트가 필요 없고 **전체 재적재**라 상태도 함께
 * 초기화된다.
 *
 * ## 「다시 시도」를 함께 두는 이유
 *
 * 일시적 원인(네트워크 응답 한 건)이면 재적재 없이 회복된다. 데이터가 원인이면
 * 같은 오류가 다시 나오는데, 그때 사용자는 옆의 이동 버튼을 쓴다.
 */
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary
      name="root"
      fallback={({ error, reset }) => (
        <ErrorScreen
          error={error}
          actions={
            <>
              <button
                type="button"
                className="error-screen__button error-screen__button--primary"
                onClick={reset}
              >
                다시 시도
              </button>
              <button
                type="button"
                className="error-screen__button"
                onClick={() => window.location.assign('/')}
              >
                처음 화면으로
              </button>
            </>
          }
        />
      )}
    >
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
