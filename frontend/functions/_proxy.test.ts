/**
 * `/api/*` 프록시의 순수 부분 검사 (#1322).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
 *
 * Worker 런타임을 띄우지 않는다. 여기서 지키려는 것은 **주소를 어떻게 옮기는가**와
 * **무엇을 넘기지 않는가**이고, 둘 다 순수 함수다. 런타임이 필요한 부분(`Set-Cookie`
 * 보존)은 `new Response(body, response)` 한 줄이라 검사로 나눌 자리가 없다.
 */

import { describe, expect, it } from 'vitest'

import { forwardableRequestHeaders, readApiOrigin, toUpstreamUrl } from './_proxy'

const ORIGIN = 'http://131.186.22.10:8001'

describe('toUpstreamUrl', () => {
  it('경로와 쿼리를 그대로 옮긴다', () => {
    expect(toUpstreamUrl('https://bluelog-bx7.pages.dev/api/v1/vessels', ORIGIN)).toBe(
      'http://131.186.22.10:8001/api/v1/vessels',
    )
    expect(
      toUpstreamUrl('https://bluelog-bx7.pages.dev/api/v1/vessels?limit=20&cursor=abc', ORIGIN),
    ).toBe('http://131.186.22.10:8001/api/v1/vessels?limit=20&cursor=abc')
  })

  it('`API_ORIGIN`에 경로가 붙어 있어도 오리진만 쓴다', () => {
    // 설정에 경로나 슬래시를 하나 더 적었다는 이유로 배포가 깨지지 않게 한다.
    //
    // ⚠️ 이 단언은 `new URL(path, base)` 구현도 통과한다 — `URL.pathname`이 언제나
    // `/`로 시작해 base의 경로가 버려지기 때문이다(돌연변이 검사로 확인했다). 즉 여기서
    // 고정하는 것은 **구현 형태가 아니라 결과**다.
    expect(toUpstreamUrl('https://pages.dev/api/v1/health', `${ORIGIN}/api/v1`)).toBe(
      'http://131.186.22.10:8001/api/v1/health',
    )
    expect(toUpstreamUrl('https://pages.dev/api/v1/health', `${ORIGIN}/`)).toBe(
      'http://131.186.22.10:8001/api/v1/health',
    )
  })

  it('인코딩된 경로를 다시 해석하지 않는다', () => {
    const url = toUpstreamUrl('https://pages.dev/api/v1/ports?q=%EC%9A%B8%EC%82%B0', ORIGIN)
    expect(url).toContain('%EC%9A%B8%EC%82%B0')
  })
})

describe('forwardableRequestHeaders', () => {
  it('쿠키를 넘긴다 — 세션과 CSRF가 이 헤더로만 전달된다', () => {
    const headers = new Headers({ cookie: 'sid=abc; csrf=def' })

    expect(forwardableRequestHeaders(headers).get('cookie')).toBe('sid=abc; csrf=def')
  })

  it('`host`를 넘기지 않는다', () => {
    // 넘기면 백엔드가 `pages.dev`를 자기 호스트로 보고, 메일 링크·리디렉트가 그 값을 탄다.
    const headers = new Headers({ host: 'bluelog-bx7.pages.dev', accept: 'application/json' })
    const forwarded = forwardableRequestHeaders(headers)

    expect(forwarded.get('host')).toBeNull()
    expect(forwarded.get('accept')).toBe('application/json')
  })

  it('Cloudflare가 붙인 헤더를 넘기지 않는다', () => {
    const headers = new Headers({
      'cf-connecting-ip': '203.0.113.7',
      'cf-ray': 'abc123',
      'content-type': 'application/json',
    })
    const forwarded = forwardableRequestHeaders(headers)

    expect(forwarded.get('cf-connecting-ip')).toBeNull()
    expect(forwarded.get('cf-ray')).toBeNull()
    expect(forwarded.get('content-type')).toBe('application/json')
  })
})

describe('readApiOrigin', () => {
  it('설정된 값을 돌려준다', () => {
    expect(readApiOrigin({ API_ORIGIN: ORIGIN })).toBe(ORIGIN)
    expect(readApiOrigin({ API_ORIGIN: `  ${ORIGIN}  ` })).toBe(ORIGIN)
  })

  it('비어 있으면 던진다 — 조용히 통과시키지 않는다', () => {
    // 통과시키면 실패가 화면에서 「로그인이 안 된다」로만 보이고, 고치려던 증상과
    // 구분되지 않는다.
    expect(() => readApiOrigin({})).toThrow(/API_ORIGIN/)
    expect(() => readApiOrigin({ API_ORIGIN: '' })).toThrow(/API_ORIGIN/)
    expect(() => readApiOrigin({ API_ORIGIN: '   ' })).toThrow(/API_ORIGIN/)
    expect(() => readApiOrigin({ API_ORIGIN: 42 })).toThrow(/API_ORIGIN/)
  })
})
