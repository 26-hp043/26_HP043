/**
 * 기능이 공유하는 HTTP 기본값 (`#1249`).
 *
 * ## 왜 공용인가
 *
 * 이 둘은 **어느 기능의 것도 아니다.** 그런데 자리가 없어 기능 폴더 안에 살았고,
 * 다른 기능들이 그것을 가리켜 **기능 사이 import가 스물다섯 곳 안팎**으로 늘었다 —
 * `voyage-cii`가 멈추면 선대·정박·챗봇이 함께 멈추는 모양이다. 화면 동작에는 드러나지
 * 않지만, 한 기능을 들어내려면 그 사슬을 먼저 풀어야 한다.
 *
 * `DEFAULT_API_BASE_URL`은 **두 곳에 따로 정의돼 있기까지 했다**(`voyage-cii` ·
 * `annual-simulation`). 같은 값을 두 곳이 들고 있으면 한쪽만 바뀌는 날이 온다.
 *
 * 숫자 표시 규약을 `display/`로 옮긴 `#392`와 같은 방식이다 — **쓰는 곳이 여럿인
 * 규약은 그 규약의 자리로 옮긴다.**
 *
 * ## 요청 래퍼는 옮기지 않았다
 *
 * 기능마다 있는 `fetch` 래퍼 열다섯은 그대로 둔다(`TECH_SPEC §16.2`). 세션 정책
 * (CSRF 헤더 · 401 처리 · 만료 문구)은 이미 `auth/session.ts` 하나에서 오므로
 * **사용자에게 드러나는 불일치가 없고**, 열다섯 파일의 네트워크 경로를 한 번에 갈아
 * 끼우는 것은 얻는 것보다 위험이 크다.
 */

/**
 * 기본 API base URL.
 * - 개발: vite 프록시를 거치므로 상대 경로 `/api/v1`이 맞다.
 * - Cloudflare Pages: `VITE_API_BASE_URL` 환경변수로 백엔드 절대 URL을 주입한다.
 */
export const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

/**
 * `meta`에서 페이지네이션 정보를 꺼낸다 (`API_SPEC §1.5`).
 *
 * 값이 없거나 형이 다르면 **「더 없음」으로 읽는다.** 커서를 지어내면 같은 페이지를
 * 무한히 다시 부른다.
 */
export function readPageMeta(body: unknown): { nextCursor: string | null; hasMore: boolean } {
  const meta = (body as { meta?: Record<string, unknown> } | null)?.meta
  const cursor = meta?.next_cursor
  const more = meta?.has_more
  return {
    nextCursor: typeof cursor === 'string' && cursor !== '' ? cursor : null,
    hasMore: more === true,
  }
}
