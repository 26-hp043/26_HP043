/**
 * `/api/*`를 백엔드로 넘기는 Pages Function (#1322).
 *
 * 화면과 API가 **같은 오리진**이 되게 하는 것이 전부다. 경위와 대안 비교는
 * `functions/_proxy.ts` 머리주석에 있다.
 *
 * `[[path]]`는 Pages Functions의 **catch-all**이라 `/api` 아래 모든 경로·모든 메서드가
 * 여기로 온다. 파일 이름이 곧 라우트이므로 별도 등록이 없다.
 */

import { forwardableRequestHeaders, readApiOrigin, toUpstreamUrl } from '../_proxy'

/** Pages Functions가 넘겨주는 문맥 — 이 함수가 쓰는 것만 적는다. */
interface ProxyContext {
  request: Request
  env: Record<string, unknown>
}

export async function onRequest(context: ProxyContext): Promise<Response> {
  const { request, env } = context

  let apiOrigin: string
  try {
    apiOrigin = readApiOrigin(env)
  } catch (error) {
    // 502로 답한다 — 게이트웨이(이 함수)가 상류를 정하지 못한 상태다. 500이면
    // 백엔드가 터진 것과 구분되지 않는다.
    return Response.json(
      {
        error: {
          code: 'PROXY_NOT_CONFIGURED',
          message: error instanceof Error ? error.message : '프록시 설정이 없습니다.',
        },
      },
      { status: 502 },
    )
  }

  const upstream = new Request(toUpstreamUrl(request.url, apiOrigin), {
    method: request.method,
    headers: forwardableRequestHeaders(request.headers),
    // `GET`·`HEAD`에는 본문이 없다. 그 밖에는 스트림을 그대로 흘린다 —
    // CSV 적재처럼 큰 본문을 메모리에 모으지 않기 위함이다.
    body: request.method === 'GET' || request.method === 'HEAD' ? null : request.body,
    redirect: 'manual',
  })

  const response = await fetch(upstream)

  // `new Response(body, response)`는 상태·상태문구·헤더를 **그대로** 옮긴다.
  // `Set-Cookie`가 여러 줄(`sid`·`csrf`)인 것도 이 경로에서 보존된다 — 헤더를 손으로
  // 복사하면 같은 이름이 하나로 합쳐져 **둘 중 하나가 사라진다.**
  //
  // 쿠키의 `Domain`은 백엔드가 지정하지 않으므로(`COOKIE_ATTRIBUTES`) 브라우저가
  // 이 응답을 준 호스트(`bluelog-bx7.pages.dev`)에 붙인다. 그것이 노리는 바다.
  return new Response(response.body, response)
}
