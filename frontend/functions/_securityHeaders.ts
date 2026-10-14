/**
 * TECH_SPEC §20 — Function 응답에는 정적 _headers가 적용되지 않는다 (#2111).
 *
 * Function이 내보내는 것은 JSON·CSV·PDF·지도 바이너리뿐이고 문서가 아니다. 그래서 화면용
 * 정책이 아니라 아무것도 불러오지 않는 정책을 쓴다 (#2368 · 백엔드 `security_headers.py`와 같은 값).
 */
export const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
} as const

export async function attachSecurityHeaders(context: { next: () => Promise<Response> }): Promise<Response> {
  const upstream = await context.next()
  // 본문 스트림·상태·쿠키·Range·캐시 헤더를 옮긴 뒤 보안 헤더만 덮어쓴다.
  const response = new Response(upstream.body, upstream)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value)
  }
  return response
}
