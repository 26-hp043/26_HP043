// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { safeNext } from './safeNext'

/**
 * `?next=` 복귀 경로 검사 (`#2127`).
 *
 * 종전 검사는 문자열 접두어(`/`로 시작 · `//`로 시작하지 않음)였고, **브라우저의 URL
 * 해석과 어긋나는 입력 셋**을 통과시켰다 — 역슬래시, 탭·개행, 점 구간. 아래 표의
 * 「거부」 행 가운데 그 셋은 수정 전 구현에서 원문 그대로 통과한다.
 *
 * jsdom에서 돈다 — 판정이 `window.location.origin`에 대한 것이기 때문이다. 창이 없는
 * 환경의 갈래는 `session.test.ts`(노드)가 같은 함수를 불러 지난다.
 */
describe('safeNext — 앱 안의 경로만 통과한다', () => {
  it.each([
    ['경로', '/x', '/x'],
    ['쿼리와 해시', '/x?y=1#z', '/x?y=1#z'],
    ['쿼리 안의 주소는 경로의 일부다', '/x?to=https://evil.com', '/x?to=https://evil.com'],
    // 인코딩된 역슬래시는 **경로 글자**다 — 브라우저가 구분자로 읽지 않는다.
    ['인코딩된 역슬래시', '/%5Cevil.com', '/%5Cevil.com'],
  ])('%s는 통과한다', (_label, raw, expected) => {
    expect(safeNext(raw)).toBe(expected)
  })

  it.each([
    ['null', null],
    ['빈 문자열', ''],
    ['프로토콜 상대 주소', '//evil.com'],
    ['역슬래시 — 브라우저는 //로 읽는다', '/\\evil.com'],
    ['역슬래시 뒤 슬래시', '/\\/evil.com'],
    ['역슬래시로 시작', '\\/evil.com'],
    ['절대 주소', 'https://evil.com'],
    ['스크립트 스킴', 'javascript:alert(1)'],
    ['탭 — URL 해석기가 지운다', '/\t/evil.com'],
    ['개행', '/\n/evil.com'],
    ['점 구간 — 접히면 //가 된다', '/.//evil.com'],
    ['상대 경로', 'dashboard'],
    ['앞 공백', ' /x'],
    ['로그인 화면 자신', '/login'],
    ['로그인 화면 자신 + 쿼리', '/login?next=/x'],
  ])('%s는 거부되고 루트로 대체된다', (_label, raw) => {
    expect(safeNext(raw)).toBe('/')
  })

  it('통과한 값은 어떤 입력에서도 현재 원점 안의 주소로 해석된다', () => {
    // 성질로 본다 — 표에 없는 우회가 생겨도 이 단언이 지키려는 것은 그대로다.
    const inputs = [
      '/x',
      '/x?y=1#z',
      '//evil.com',
      '/\\evil.com',
      '/\\/evil.com',
      '\\/evil.com',
      'https://evil.com',
      'javascript:alert(1)',
      '/\t/evil.com',
      '/%5Cevil.com',
      '',
      '/.//evil.com',
      '/..//evil.com',
      '/%2F/evil.com',
      '/x/../..//evil.com',
      '/login',
    ]
    for (const raw of inputs) {
      const out = safeNext(raw)
      expect(new URL(out, window.location.origin).origin).toBe(window.location.origin)
      expect(out.startsWith('/')).toBe(true)
      expect(out.startsWith('//')).toBe(false)
    }
  })
})
