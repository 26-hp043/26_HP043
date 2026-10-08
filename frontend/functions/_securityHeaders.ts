/** TECH_SPEC §20 — Function 응답에는 정적 _headers가 적용되지 않는다 (#2111). */
export const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
} as const

export async function onRequest(context: { next: () => Promise<Response> }): Promise<Response> {
  const upstream = await context.next()
  // 본문 스트림·상태·쿠키·Range·캐시 헤더를 옮긴 뒤 세 헤더만 덮어쓴다.
  const response = new Response(upstream.body, upstream)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value)
  }
  return response
}
