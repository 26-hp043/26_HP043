import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 죽은 CSS 클래스가 다시 쌓이지 않게 한다 (#831 ⑶).
 *
 * ## 왜 필요한가
 *
 * 화면을 개편하면 마크업은 바뀌는데 **CSS는 남는다.** 남은 규칙은 아무것도 하지
 * 않으므로 화면이 깨지지 않고, 그래서 발견되지 않는다. 실제로 `AnnualSimulation.css`
 * 하나에 **26개**가 쌓여 있었다 — 다음 사람이 그 파일을 열면 지금 화면에 없는 구조를
 * 근거로 삼게 된다.
 *
 * ## 동적 조립을 죽은 것으로 세지 않는다
 *
 * `` className={`seg seg--${rating}`} `` 처럼 만드는 이름은 소스에 완성형으로 나타나지
 * 않는다. 접두(`seg--`)가 템플릿 리터럴에 있으면 그 접두로 시작하는 클래스는 살아 있는
 * 것으로 본다 — **감추는 쪽이 아니라 놓치는 쪽으로 기운다.**
 *
 * ## 주석은 보지 않는다
 *
 * CSS 주석에 적힌 `grid.gnb-expanded` 같은 문구가 선택자로 잡혔다. 실제로 겪은 오탐이라
 * 주석을 먼저 걷어낸다.
 */
const SRC = new URL('.', import.meta.url).pathname

/** 의도적으로 남긴 것. 지우려면 근거 주석과 함께 여기서도 빼야 한다. */
const KEPT: Readonly<Record<string, string>> = {
  // `AppShell.tsx:40-42` — "접힘 동작 자체는 MVP 범위 밖 … 나중에 셸을 다시 만들지
  // 않기 위한 준비". 의도를 코드가 밝히고 있어 유지가 맞다.
  'app-shell--collapsed': 'AppShell.tsx:40-42 — MVP 범위 밖, 준비된 자리',
}

/** 블록·줄 주석을 걷어낸다. 문자열 안의 `//`까지 지우지만, 여기서는 이름만 세므로 무해하다. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : walk(path)
    return [path]
  })
}

/*
 * 결과를 기억한다. 두 검사가 각각 부르면 `src/` 전체를 **두 번** 읽어 5초 제한을
 * 넘는다 — 실제로 넘겼다. 읽는 대상이 같으므로 한 번이면 된다.
 */
const cache = new Map<boolean, string[]>()

function deadClasses(options: { applyKept?: boolean } = {}): string[] {
  const applyKept = options.applyKept ?? true
  const cached = cache.get(applyKept)
  if (cached) return cached
  const files = walk(SRC)
  /*
   * **소스의 주석도 걷어낸다.** 안 그러면 「이 클래스는 지금 안 쓴다」고 적어 둔 주석
   * 자체가 사용 근거가 되어, 정작 그런 클래스가 잡히지 않는다 —
   * `.app-shell--collapsed`가 실제로 그랬다.
   */
  const code = files
        // **검사 파일은 제외한다.** 아래 `KEPT`가 클래스 이름을 문자열로 담고 있어,
    // 넣으면 이 파일 자신이 「사용 근거」가 되어 보존 목록이 언제나 낡지 않은 것으로 나온다.
    .filter((f) => /\.tsx?$/.test(f) && !f.includes('.test.'))
    .map((f) => stripComments(readFileSync(f, 'utf8')))
    .join('\n')

  const used = new Set(code.match(/[A-Za-z][\w-]*/g) ?? [])
  const dynamicPrefixes = [...code.matchAll(/([A-Za-z][\w-]*?(?:--|__))\$\{/g)].map((m) => m[1])

  const dead: string[] = []
  for (const file of files.filter((f) => f.endsWith('.css'))) {
    const css = readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      // `@import './tokens.generated.css'`의 **파일명**이 선택자로 잡힌다.
      .replace(/@import[^;]*;/g, '')
    for (const match of css.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) {
      const cls = match[1]
      if (used.has(cls)) continue
      if (applyKept && cls in KEPT) continue
      if (dynamicPrefixes.some((prefix) => cls.startsWith(prefix))) continue
      dead.push(`${file.slice(SRC.length)} :: .${cls}`)
    }
  }
  const result = [...new Set(dead)].sort()
  cache.set(applyKept, result)
  return result
}

/*
 * 기본 5초로는 모자란다 — `src/` 전체(.css + .ts/.tsx)를 읽고 주석을 걷어낸다.
 * 트리가 커지면 더 걸리므로 여유를 둔다. **줄이려고 대상을 좁히지 않는다** — 훑지
 * 않은 파일이 곧 놓치는 파일이다.
 */
const SCAN_TIMEOUT_MS = 20_000

describe('죽은 CSS 클래스 (#831)', () => {
  it('참조되지 않는 클래스가 없다', { timeout: SCAN_TIMEOUT_MS }, () => {
    expect(deadClasses()).toEqual([])
  })

  it('보존 목록이 낡지 않았다 — 참조가 생긴 것은 뺀다', { timeout: SCAN_TIMEOUT_MS }, () => {
    // `moduleBoundary.test.ts`가 미참조 export에 대해 하는 것과 같은 규율이다.
    // 보존 목록을 **적용하지 않은** 결과로 본다 — 적용하면 KEPT 항목이 결과에서
    // 빠져 이 검사가 언제나 통과한다.
    const measured = new Set(
      deadClasses({ applyKept: false }).map((entry) => entry.split(':: .')[1]),
    )
    const stale = Object.keys(KEPT).filter((cls) => !measured.has(cls))
    expect(stale).toEqual([])
  })
})
