import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 접근성 배선의 회귀를 막는다 (#829 ⑸).
 *
 * ## 왜 소스로 보는가
 *
 * 이 성질들은 **화면이 깨지지 않는다.** `role`을 빼도 그림은 그대로이고, 달라지는
 * 것은 낭독뿐이라 눈으로도 기존 검사로도 드러나지 않는다. 그래서 소스에서 본다 —
 * `moduleBoundary.test.ts`·`deadCss.test.ts`와 같은 규율이다.
 */
const SRC = new URL('.', import.meta.url).pathname

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sources(path)
    if (!/\.tsx$/.test(name) || name.includes('.test.')) return []
    return [path]
  })
}

const FILES = sources(SRC).map((path) => ({ path: path.slice(SRC.length), text: readFileSync(path, 'utf8') }))

describe('접근성 배선 (#829 ⑸)', () => {
  it('검증 오류 문구에 role="alert"가 있다', () => {
    /*
     * 없으면 **검증 실패가 아무것도 안 읽힌다.** 화면에는 빨간 글씨가 떠 있는데
     * 스크린 리더 쪽에서는 제출이 조용히 실패한 것으로 보인다. 26곳이 그 상태였다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(span|em|p)\s+className="[a-z-]+__field-error"([^>]*)>/g)) {
        if (!match[2].includes('role="alert"')) offenders.push(`${path} :: ${match[0].trim()}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('role 없는 요소에 aria-label을 걸지 않는다', () => {
    /*
     * `role`이 없는 `<span>`·`<div>`의 `aria-label`은 **무시된다.** 라벨을 적어 둔
     * 사람은 읽힌다고 믿는데 실제로는 아무 이름도 없다.
     *
     * 조건부 라벨(`aria-label={x ? … : undefined}`)은 `role`도 같은 조건이면 되므로,
     * 여기서는 **`role=`이라는 낱말이 같은 태그 안에 있는지**만 본다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(span|div|p|li|ul)\s([^>]*)>/g)) {
        /*
         * **속성 자리의 주석을 걷어낸다.** 「`role="img"`가 있어야 읽힌다」고 적어 둔
         * 주석이 그 자체로 `role=`을 담아, 정작 속성이 빠졌을 때 잡히지 않았다 —
         * `deadCss.test.ts`에서 겪은 것과 같은 함정이다.
         */
        const attrs = match[2].replace(/\/\*[\s\S]*?\*\//g, '')
        if (attrs.includes('aria-label') && !attrs.includes('role=')) {
          offenders.push(`${path} :: <${match[1]}>`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('본문 바로가기 링크가 있고 main이 초점을 받는다', () => {
    // 없으면 매 화면 진입마다 사이드바 항목을 전부 Tab으로 지나야 한다 (WCAG 2.4.1).
    const shell = FILES.find((f) => f.path.endsWith('layout/AppShell.tsx'))
    expect(shell, 'AppShell.tsx를 찾지 못했습니다').toBeDefined()
    expect(shell!.text).toContain('className="skip-link"')
    expect(shell!.text).toMatch(/<main[^>]*tabIndex=\{-1\}/)
  })

  it('라우트가 바뀌면 문서 제목을 갱신한다', () => {
    // SPA는 문서를 다시 읽지 않는다. 갱신하지 않으면 화면이 바뀐 것을 알 수단이 없다.
    const shell = FILES.find((f) => f.path.endsWith('layout/AppShell.tsx'))!
    expect(shell.text).toContain('document.title =')
  })

  it('로딩 문구가 라이브 리전 안에 있다', () => {
    /*
     * `aria-busy` **단독은 아무것도 알리지 않는다.** 「불러오는 중입니다…」가 화면에
     * 떠도 낭독되지 않으면, 사용자는 눌렀는데 아무 일도 없는 것으로 읽는다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(p|em|span)\s+([^>]*aria-busy="true"[^>]*)>/g)) {
        if (!match[2].includes('role="status"')) offenders.push(`${path} :: <${match[1]}>`)
      }
    }
    expect(offenders).toEqual([])
  })
})
