/**
 * Cloudflare Pages Functions — `/api/*` 프록시의 순수 부분 (#1322).
 *
 * ## 왜 프록시인가
 *
 * 종전 배포는 화면이 `https://bluelog-bx7.pages.dev`, API가
 * `http://131.186.22.10:8001`이었다. **세 겹으로 막힌다.**
 *
 * 1. https 페이지에서 http로 가는 fetch는 브라우저가 **혼합 콘텐츠로 차단**한다 —
 *    요청 자체가 나가지 않는다.
 * 2. 설령 나가도 `Secure` 쿠키는 **http 응답의 `Set-Cookie`에서 거부**된다
 *    (`auth/session.py`의 `COOKIE_ATTRIBUTES`). `localhost` 예외는 IP에 해당하지 않는다.
 * 3. `SameSite=Lax` 쿠키는 `pages.dev` → `131.186.22.10` **교차 사이트 fetch에 실리지
 *    않는다.** 백엔드에 TLS를 붙여도(`#786`) `SameSite=None`으로 바꾸기 전에는 같다.
 *
 * 같은 오리진으로 되돌리면 **세 겹이 한꺼번에 사라진다.** 브라우저는 https로 자기
 * 자신에게만 말하고, 쿠키는 `Secure`·`Lax` 그대로 성립한다 — **백엔드와 `API_SPEC §1.2`를
 * 건드리지 않는다.** 교차 오리진을 유지하는 쪽은 `samesite="none"` + 백엔드 TLS +
 * CORS 자격 증명을 함께 바꿔야 해서 훨씬 넓다.
 *
 * ## 왜 `_redirects`가 아닌가
 *
 * Pages의 `_redirects` 200 재작성은 **같은 사이트 내부 경로만** 가능하다. 외부 오리진을
 * 가리키면 재작성이 아니라 리디렉트가 되어 브라우저가 다시 http로 간다 — 1번이 그대로다.
 *
 * ## 이 파일이 라우트가 아닌 이유
 *
 * `_`로 시작하는 파일은 Pages Functions의 **라우트로 등록되지 않는다.** 순수 함수만 두어
 * `_proxy.test.ts`가 Worker 런타임 없이 검사할 수 있게 한다.
 */

/**
 * 원 클라이언트 IP를 백엔드에 전하는 헤더와, 그 값을 이 프록시가 붙였다는 증표 (#1483).
 *
 * 이름은 백엔드 `api/rate_limit.py`의 `CLIENT_IP_HEADER`·`PROXY_SECRET_HEADER`와 같아야 한다.
 *
 * ## 왜 `cf-connecting-ip`를 그대로 넘기지 않는가
 *
 * 화면(`pages.dev`)과 API(터널 호스트)는 **다른 Cloudflare 영역**이다. 영역 사이
 * 서브리퀘스트에는 Cloudflare가 `CF-Connecting-IP`를 Worker 주소 `2a06:98c0:3600::103`
 * 하나로 다시 쓴다(Cloudflare Docs *HTTP headers*). 그 이름으로는 원 IP가 도착하지 않는다.
 * 그래서 브라우저 요청에 붙어 온 값(엣지가 붙인 것 — 사용자가 위조하지 못한다)을
 * **우리 이름으로 옮겨 담는다.**
 */
export const CLIENT_IP_HEADER = 'x-bluelog-client-ip'
export const PROXY_SECRET_HEADER = 'x-bluelog-proxy-secret'

/** 프록시가 그대로 흘리지 않는 요청 헤더. */
const DROPPED_REQUEST_HEADERS = new Set([
  // 업스트림 주소로 다시 계산돼야 한다 — 그대로 넘기면 백엔드가 `pages.dev`를 자기
  // 호스트로 본다.
  'host',
  // Cloudflare가 붙이는 값. 백엔드가 해석하지 않고, 남겨 두면 어느 쪽이 붙인
  // 것인지 읽는 사람이 가릴 수 없다.
  'cf-connecting-ip',
  'cf-ipcountry',
  'cf-ray',
  'cf-visitor',
  // 아래 두 이름은 **이 프록시만 붙인다** (#1483). 브라우저가 같은 이름으로 보내 오면
  // 떼어 낸다 — 그대로 흘리면 비밀 값을 모르는 사람이 원 IP 자리를 채울 수 있다.
  CLIENT_IP_HEADER,
  PROXY_SECRET_HEADER,
])

/**
 * 브라우저가 부른 주소를 업스트림 주소로 옮긴다.
 *
 * 경로와 쿼리는 **그대로** 둔다 — 화면이 `/api/v1/...`로 부르고 백엔드도
 * `/api/v1/...`로 받으므로 다시 쓸 것이 없다.
 *
 * @param requestUrl 브라우저가 부른 절대 주소 (`https://…/api/v1/vessels?limit=20`)
 * @param apiOrigin  백엔드 오리진 (`http://131.186.22.10:8001`) — 경로가 붙어 있어도 버린다
 */
export function toUpstreamUrl(requestUrl: string, apiOrigin: string): string {
  const incoming = new URL(requestUrl)
  const upstream = new URL(apiOrigin)
  // **오리진만 취한다.** `apiOrigin`에 경로가 섞여 들어와도(`…:8001/api/v1`) 그 경로는
  // 버린다 — 넘길 경로는 브라우저가 부른 쪽이 전부 갖고 있다.
  //
  // ⚠️ `new URL(incoming.pathname + incoming.search, apiOrigin)`으로 써도 **결과는 같다.**
  // `URL.pathname`은 언제나 `/`로 시작하므로 base의 경로가 버려지기 때문이다. 처음에는
  // 「그렇게 쓰면 `/api/v1`이 두 번 붙는다」고 적었는데 **거짓이었고, 돌연변이 검사가
  // 그 주석을 잡았다**(그 변형이 검출되지 않았다 — 동치이므로 당연하다). 이 형태를
  // 고른 이유는 동작 차이가 아니라 **읽는 사람이 오리진만 쓴다는 것을 한눈에 보는 것**이다.
  return `${upstream.origin}${incoming.pathname}${incoming.search}`
}

/**
 * 업스트림으로 넘길 요청 헤더를 고른다.
 *
 * **쿠키는 그대로 넘긴다.** 같은 오리진이므로 브라우저가 `sid`·`csrf`를 실어 주고,
 * 백엔드는 그 둘로 세션과 CSRF를 판정한다.
 */
export function forwardableRequestHeaders(headers: Headers): Headers {
  const out = new Headers()
  headers.forEach((value, key) => {
    if (!DROPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      out.set(key, value)
    }
  })
  return out
}

/**
 * ``API_ORIGIN``이 설정돼 있는지 본다.
 *
 * **비어 있으면 조용히 통과시키지 않는다.** 값이 없으면 프록시가 자기 자신을 부르거나
 * 알 수 없는 주소로 가는데, 그 실패는 화면에서 「로그인이 안 된다」로만 보인다 —
 * `#1322`가 고치려는 증상과 구분되지 않는다. 설정 누락임을 그 자리에서 말한다.
 */
export function readApiOrigin(env: Record<string, unknown>): string {
  const raw = typeof env.API_ORIGIN === 'string' ? env.API_ORIGIN.trim() : ''
  if (!raw) {
    throw new Error(
      'API_ORIGIN이 설정되지 않았습니다. frontend/wrangler.toml의 [vars] 또는 ' +
        'Cloudflare Pages 프로젝트 환경변수에 백엔드 오리진을 넣으세요 (#1322).',
    )
  }
  return raw
}

/**
 * 프록시와 백엔드가 나눠 가진 비밀 값 (#1483). 없으면 빈 문자열.
 *
 * `API_ORIGIN`과 달리 **없어도 던지지 않는다** — 없으면 원 IP를 싣지 않을 뿐이고
 * 백엔드는 종전 규칙으로 센다. 요청을 막을 이유가 아니다. 비밀 값은 `wrangler.toml`에
 * 두지 않는다(저장소에 공개된다) — 배포가 `wrangler pages secret put`으로 넣는다.
 */
export function readProxySecret(env: Record<string, unknown>): string {
  return typeof env.PROXY_CLIENT_IP_SECRET === 'string' ? env.PROXY_CLIENT_IP_SECRET.trim() : ''
}

/**
 * 원 클라이언트 IP와 비밀 값을 업스트림 헤더에 싣는다 (#1483).
 *
 * 비밀 값이나 원 IP 중 하나라도 없으면 **아무것도 싣지 않는다.** 반쪽만 실으면 백엔드는
 * 어차피 무시하지만, 읽는 사람이 「왜 IP만 있는가」를 따로 추적해야 한다.
 *
 * @param upstream   `forwardableRequestHeaders`가 고른 헤더 — 여기에 덧붙인다
 * @param incoming   브라우저 요청의 원래 헤더 (`cf-connecting-ip`를 읽는다)
 * @param secret     `readProxySecret`의 결과
 */
export function attachClientIp(upstream: Headers, incoming: Headers, secret: string): Headers {
  const ip = (incoming.get('cf-connecting-ip') ?? '').trim()
  if (secret && ip) {
    upstream.set(CLIENT_IP_HEADER, ip)
    upstream.set(PROXY_SECRET_HEADER, secret)
  }
  return upstream
}
