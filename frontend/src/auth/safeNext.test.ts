// @vitest-environment jsdom
import '../test/renderSetup'

import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { SCREEN_BY_ID } from '../screens'
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
    // 로그인 화면이 **아닌** 것은 이름이 비슷해도 통과한다.
    ['로그인 실패 화면', '/login/failure', '/login/failure'],
    ['로그인으로 시작하는 다른 경로', '/loginx', '/loginx'],
    ['가입 화면 — 세션이 있으면 스스로 기본 화면으로 떠난다', '/signup', '/signup'],
  ])('%s는 통과한다', (_label, raw, expected) => {
    expect(safeNext(raw)).toBe(expected)
  })

  /*
   * 로그인 화면 자신은 **라우터와 같은 판정**으로 거부한다. 라우터가 대소문자·끝 슬래시·
   * 인코딩을 가리지 않으므로(아래 describe가 실제 라우터로 확인한다) 문자열 일치로는
   * 빠져나간다.
   */
  it.each([
    ['끝 슬래시', '/login/'],
    ['대문자', '/LOGIN'],
    ['섞인 대소문자 + 쿼리', '/Login/?next=/x'],
    ['인코딩된 글자', '/%6Cogin'],
    ['해시만 붙음', '/login#x'],
  ])('로그인 화면의 다른 표기(%s)도 거부한다', (_label, raw) => {
    expect(safeNext(raw)).toBe('/')
  })

  it.each([
    ['숫자', 1],
    ['배열', ['/x']],
    ['객체', { toString: () => '/x' }],
    ['undefined', undefined],
  ])('문자열이 아닌 값(%s)은 던지지 않고 루트로 대체된다', (_label, raw) => {
    expect(safeNext(raw as unknown as string)).toBe('/')
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

/*
 * 위 거부 표의 전제 — **이 앱의 라우터는 그 표기들을 실제로 로그인 화면에 닿게 한다.**
 * `App.tsx`의 라우트는 옵션 없이 `path`만 준다(`caseSensitive` 미지정). 전제가 바뀌면
 * (라우터를 대소문자 구분으로 바꾸는 등) 이 검사가 먼저 알린다.
 */
describe('라우터는 로그인 경로의 다른 표기를 로그인 화면에 맞춘다', () => {
  const landsOnLogin = (path: string): boolean => {
    const { container, unmount } = render(
      createElement(
        MemoryRouter,
        { initialEntries: [path] },
        createElement(
          Routes,
          null,
          createElement(Route, {
            path: SCREEN_BY_ID.LOGIN.path,
            element: createElement('p', { 'data-login': '' }),
          }),
          createElement(Route, { path: '*', element: createElement('p', { 'data-other': '' }) }),
        ),
      ),
    )
    const landed = container.querySelector('[data-login]') !== null
    unmount()
    return landed
  }

  it.each(['/login', '/login/', '/LOGIN', '/Login/', '/%6Cogin'])('%s → 로그인 화면', (path) => {
    expect(landsOnLogin(path)).toBe(true)
  })

  it.each(['/login/failure', '/loginx', '/signup'])('%s → 다른 화면', (path) => {
    expect(landsOnLogin(path)).toBe(false)
  })

  it('라우터가 로그인 화면에 맞추는 표기는 전부 복귀 경로로 거부된다', () => {
    for (const path of ['/login', '/login/', '/LOGIN', '/Login/', '/%6Cogin']) {
      expect(landsOnLogin(path)).toBe(true)
      expect(safeNext(path)).toBe('/')
    }
  })
})
