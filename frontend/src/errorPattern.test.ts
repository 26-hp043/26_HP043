import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/*
 * `rlatnals4114`의 2026-09-10 확정 문서가 정한 규격을 잠그는 가드 2건.
 * **규격은 확정자가 정했고 개발은 가드만 만들었다**(`AGENTS §7.3`). 소스로 본다 — **화면이 깨지지 않는 성질**이라
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

  /*
   * **토큰 그래프를 끝까지 펼쳐** 본다 (2026-09-11 확정 H).
   *
   * 종전에는 선언 문자열에서 `var(--cii-`만 찾았다. 그러면 **등급 토큰을 가리키는
   * 별칭**을 쓰는 순간 통과한다 — `--color-warning`은 `--cii-c-fill`의 별칭이다.
   * 브랜드 판의 「테마 불변」 가드가 별칭 한 겹 아래의 갈라짐을 못 본 것(`#608`)과
   * 같은 함정이라, 선언이 가리키는 사슬을 전부 따라가 `--cii-*`에 닿는지 본다.
   */
  const cssFiles = files.filter((f) => f.endsWith('.css'))
  const stripped = (file: string) => readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

  // 모든 CSS의 커스텀 프로퍼티 선언 — 테마 블록마다 값이 다를 수 있어 **전부** 모은다.
  const graph = new Map<string, string[]>()
  for (const file of cssFiles) {
    for (const [, name, value] of stripped(file).matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)) {
      graph.set(name, [...(graph.get(name) ?? []), value])
    }
  }

  /** `expression`이 가리키는 사슬 중 `--cii-*`에 닿는 첫 경로. 없으면 `null`. */
  function reachesGrade(expression: string, seen: Set<string> = new Set()): string | null {
    for (const [, name] of expression.matchAll(/var\(\s*(--[\w-]+)/g)) {
      if (name.startsWith('--cii-')) return name
      if (seen.has(name)) continue
      seen.add(name)
      for (const value of graph.get(name) ?? []) {
        const hit = reachesGrade(value, seen)
        if (hit) return `${name} → ${hit}`
      }
    }
    return null
  }

  it('토큰 그래프를 실제로 읽었다 — 별칭이 등급 토큰에 닿는 것을 알아본다', () => {
    // 수집이 깨지면 아래 검사가 전부 통과한다. 알려진 별칭 하나로 먼저 확인한다.
    expect(reachesGrade('var(--color-warning)')).toContain('--cii-c-fill')
    expect(reachesGrade('var(--surface-card)')).toBeNull()
  })

  it('실패 표시에 등급 토큰(`--cii-*`)을 쓰지 않는다 — 별칭을 거쳐도', () => {
    /*
     * 종전 `.empty--error`가 **등급 E 토큰**을 쓰고 있었고, 그 코드가 살아 있는
     * 화면이 하필 **등급을 보여 주는 선박 상세**였다 — 「불러오지 못했습니다」가
     * 「이 배는 E등급입니다」로 읽힌다 (`§0.2` 제약 2).
     */
    const offenders: string[] = []
    for (const file of cssFiles) {
      // 규칙 단위로 본다 — 선택자에 error가 있는 블록만.
      for (const match of stripped(file).matchAll(/([^{}]*)\{([^}]*)\}/g)) {
        if (!/error/i.test(match[1])) continue
        const hit = reachesGrade(match[2])
        if (hit) offenders.push(`${file.slice(SRC.length)} :: ${match[1].trim()} :: ${hit}`)
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
