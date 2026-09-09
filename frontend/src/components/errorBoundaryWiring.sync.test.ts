/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/*
 * ⚠️ **jsdom을 쓰지 않는다.** 다른 `*.sync.test.ts`와 같다 — jsdom 환경에서는
 * `import.meta.url`이 파일 URL이 아니라 `readFileSync`가 던진다. 이 파일은 소스를
 * 읽기만 하므로 DOM이 필요 없다.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))

/*
 * 루트 배선 가드 (`#823`).
 *
 * ## 왜 소스를 읽는가
 *
 * `main.tsx`는 진입점이라 **어떤 테스트도 import하지 않는다** — `createRoot`가 실제
 * DOM 노드를 요구한다. 그래서 루트 경계를 통째로 지워도 검사 1162건이 전부
 * 통과했다(실측). 화면 단위 경계는 `AppShell.test.tsx`가 진짜 렌더로 잠그지만,
 * 루트는 그럴 자리가 없다.
 *
 * `screens.test.ts`의 `isComingSoonStub()`이 페이지 파일 소스를 읽어 스텁 여부를
 * 가리는 것과 같은 방식이다 — **검사할 수 없는 자리에는 소스 대조를 둔다.**
 *
 * ## 무엇을 보는가
 *
 * 「`<App/>`이 `ErrorBoundary` 안에 있는가」 하나다. 문구·버튼 구성은 위 검사들이
 * 이미 본다. 여기서 더 보면 `main.tsx`를 손댈 때마다 무관하게 깨진다.
 */
describe('루트 경계가 실제로 배선돼 있다 (#823)', () => {
  const source = readFileSync(join(HERE, '..', 'main.tsx'), 'utf-8')

  it('`main.tsx`가 `ErrorBoundary`를 import한다', () => {
    expect(source).toMatch(/import\s*\{[^}]*ErrorBoundary[^}]*\}\s*from\s*'\.\/components\/ErrorBoundary'/)
  })

  it('`<App />`이 경계 **안**에 있다', () => {
    const open = source.indexOf('<ErrorBoundary')
    const app = source.indexOf('<App />')
    const close = source.indexOf('</ErrorBoundary>')

    expect(open, '`main.tsx`에 ErrorBoundary가 없다 — 렌더 예외가 앱을 백지로 만든다').toBeGreaterThan(-1)
    expect(app, '`main.tsx`에 <App />이 없다 — 이 검사의 전제가 깨졌다').toBeGreaterThan(-1)
    expect(close).toBeGreaterThan(app)
    expect(app, '<App />이 ErrorBoundary 밖에 있다 — 라우터·셸의 예외를 받지 못한다').toBeGreaterThan(open)
  })

  it('라우터에 기대지 않는 이동 수단이 있다 — `Link`는 컨텍스트를 요구한다', () => {
    /*
     * 루트 경계가 잡는 예외는 **라우터가 살아 있지 않을 수 있다.** 오류 화면이
     * `<Link>`를 쓰면 그 화면 자체가 다시 던져 경계가 무의미해진다.
     */
    expect(source).toContain('window.location')
    /*
     * 「`<Link>`를 안 쓴다」가 아니라 **「라우터를 import하지 않는다」**로 본다.
     * 전자는 주석 안의 `<Link>` 언급까지 잡는다 — 실제로 이 파일의 docstring이
     * 「왜 `<Link>`가 아닌가」를 설명하고 있어 처음에 그렇게 걸렸다.
     */
    expect(source).not.toMatch(/from ['"]react-router['"]/)
  })
})
