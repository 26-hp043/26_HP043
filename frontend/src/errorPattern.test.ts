import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/*
 * 확정 문서의 재발 방지 가드 2건. 소스로 본다 — **화면이 깨지지 않는 성질**이라
 * 렌더 검사로는 잡히지 않는다.
 */
const SRC = new URL('.', import.meta.url).pathname

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sources(path)
    return [path]
  })
}

describe('에러 표현 규격 가드 (#694)', () => {
  const files = sources(SRC)

  it('실패 표시에 등급 토큰(`--cii-*`)을 쓰지 않는다', () => {
    /*
     * 종전 `.empty--error`가 **등급 E 토큰**을 쓰고 있었고, 그 코드가 살아 있는
     * 화면이 하필 **등급을 보여 주는 선박 상세**였다 — 「불러오지 못했습니다」가
     * 「이 배는 E등급입니다」로 읽힌다 (`§0.2` 제약 2).
     */
    const offenders: string[] = []
    for (const file of files.filter((f) => f.endsWith('.css'))) {
      const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
      // 규칙 단위로 본다 — 선택자에 error가 있는 블록만.
      for (const match of css.matchAll(/([^{}]*)\{([^}]*)\}/g)) {
        if (!/error/i.test(match[1])) continue
        if (/var\(--cii-/.test(match[2])) {
          offenders.push(`${file.slice(SRC.length)} :: ${match[1].trim()}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('실패 표시가 전역 클래스를 확장하지 않는다', () => {
    /*
     * `.empty--error`는 전역 `.empty`를 확장한 것이었다. 그러면 실패 표시를 고칠
     * 때마다 빈 상태가 함께 흔들린다 — CSS 구조 개편이 규격을 막지 않도록 갈랐다.
     */
    /*
     * **주석을 걷어낸다.** 「종전 `.empty--error`가 …」라고 적어 둔 설명 자체가
     * 그 문자열을 담아, 정작 클래스가 되살아나도 구분되지 않는다 — `#831`·`#829`에서
     * 두 번 겪은 함정이다.
     */
    const offenders = files
      .filter((f) => (f.endsWith('.css') || f.endsWith('.tsx')) && !f.includes('.test.'))
      .filter((f) =>
        readFileSync(f, 'utf8')
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .replace(/(^|[^:])\/\/.*$/gm, '$1')
          .includes('empty--error'),
      )
      .map((f) => f.slice(SRC.length))
    expect(offenders).toEqual([])
  })
})
