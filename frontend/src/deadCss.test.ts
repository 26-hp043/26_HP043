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
      // 같은 이유로 `url(...)` 안의 **확장자**도 잡힌다 — `#925`의
      // `url('/fonts/noto-sans-kr-400.woff2')`가 `.woff2` 클래스로 읽혀 CI가 실패했다.
      // `url()`의 인자는 경로이지 선택자가 아니다.
      .replace(/url\([^)]*\)/g, 'url()')
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

/**
 * 반대 방향 — **쓰는데 정의가 없는 클래스** (`#1052`).
 *
 * 위 검사는 「정의됐는데 아무도 안 쓴다」만 본다. 그 짝이 비어 있어 **정의를 지워도
 * 아무 검사도 실패하지 않았다.**
 *
 * 실제로 두 번 났다.
 *
 * * `.annual-sim__label` — `#1182`가 폼 라벨 넷을 공용 `Field`로 옮기며 규칙을
 *   지웠는데 **폼 밖의 네 곳**(`Metric`·예상 등급·감축 목표·위험도)이 남아 있었다
 * * `.fleet__note` — 처음부터 규칙 없이 이름만 붙었다 (`#1052` ⑴ ⒜)
 *
 * 둘 다 **화면이 깨지지 않는다.** 브라우저 기본 문단으로 그려질 뿐이라 눈으로 찾지
 * 않으면 남는다 — 죽은 CSS와 정확히 같은 성질이고, 그래서 같은 파일에 둔다.
 */

/** 규칙이 없어도 되는 것. 넣으려면 **왜 없어도 되는지**를 함께 적는다. */
const NO_STYLE: Readonly<Record<string, string>> = {
  // `card`·`fr__table`이 모양을 준다 — 이쪽은 BEM 블록 이름표다.
  dq__summary: 'card가 모양을 준다 — 블록 이름표',
  dq__vessels: 'card가 모양을 준다 — 블록 이름표',
  rp__preview: 'card가 모양을 준다 — 블록 이름표',
  vm: 'card가 모양을 준다 — 블록 이름표',
  fr__dist: 'fr__table이 모양을 준다 — 블록 이름표',
  // 자식이 각자 모양을 갖는 껍데기.
  'vessel-registration__header': '자식(title·lead)이 각자 모양을 갖는다',
  // 보이지 않는 자리 표시 — `aria-busy`만 들고 있다.
  'require-auth__pending': '보이지 않는 자리 표시(aria-busy 전용)',
  // 등급 색을 `fill` 속성으로 직접 받는다 — CSS로 줄 것이 없다.
  history__bar: 'fill을 인라인으로 받는다(등급 색)',
}

/**
 * ⚠️ **규칙이 없어도 되는지 아직 모르는 것.** 위 목록과 달리 **근거가 아니라 미제**다.
 *
 * 둘 다 고치면 화면의 크기·모양이 눈에 띄게 바뀌므로, 값을 임의로 고르지 않고
 * 자리를 만들어 둔다. 비면 이 목록도 지운다.
 */
const UNSTYLED_TODO: Readonly<Record<string, string>> = {
  // `__title-en`(형제 span)에는 규칙이 있는데 `__title` 자신에는 없다. `<h2>`가
  // 브라우저 기본 크기(2em)로 그려진다 — 다른 화면은 `card__title`을 쓴다.
  'scenario-comparison__title': '항로 비교 결과 제목 — h2가 브라우저 기본 크기다',
}

/** `className`에 **완성형으로** 적힌 이름만 모은다. 동적 조립 조각은 세지 않는다. */
function classesUsedInMarkup(): Map<string, Set<string>> {
  const used = new Map<string, Set<string>>()
  for (const file of walk(SRC)) {
    if (!file.endsWith('.tsx') || file.includes('.test.')) continue
    const source = stripComments(readFileSync(file, 'utf8'))
    for (const match of source.matchAll(/className=(?:"([^"]*)"|\{\s*[`'"]([^`'"]*)[`'"])/g)) {
      /*
       * **`${` 앞까지만 본다.** 정규식이 템플릿을 따옴표에서 끊으므로 그 뒤 조각은
       * 클래스가 아니라 **식의 일부**다 — `vm__cell--num${value === null ? …`에서
       * `null`이 클래스로 잡혔다.
       */
      const literal = (match[1] ?? match[2] ?? '').split('${')[0]
      for (const cls of literal.split(/\s+/)) {
        // `seg--`처럼 `${`를 앞둔 조각과 빈 토큰을 버린다.
        if (cls === '' || cls.endsWith('--') || cls.endsWith('__')) continue
        if (!/^-?[A-Za-z_][\w-]*$/.test(cls)) continue
        const at = used.get(cls) ?? new Set<string>()
        at.add(file.slice(SRC.length))
        used.set(cls, at)
      }
    }
  }
  return used
}

function definedClasses(): Set<string> {
  const defined = new Set<string>()
  for (const file of walk(SRC)) {
    if (!file.endsWith('.css')) continue
    const css = readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/@import[^;]*;/g, '')
      .replace(/url\([^)]*\)/g, 'url()')
    for (const match of css.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) defined.add(match[1])
  }
  return defined
}

describe('규칙 없는 CSS 클래스 (#1052)', () => {
  it('마크업이 쓰는 클래스에 규칙이 있다', { timeout: SCAN_TIMEOUT_MS }, () => {
    const defined = definedClasses()
    const orphans: string[] = []
    for (const [cls, files] of classesUsedInMarkup()) {
      if (defined.has(cls)) continue
      if (cls in NO_STYLE || cls in UNSTYLED_TODO) continue
      orphans.push(`.${cls} :: ${[...files].sort().join(', ')}`)
    }
    expect(
      orphans.sort(),
      '규칙이 없으면 브라우저 기본 모양으로 그려진다. 일부러 비워 둔 것이라면 ' +
        'NO_STYLE에 이유와 함께 적어 두세요.',
    ).toEqual([])
  })

  it('두 목록이 낡지 않았다 — 규칙이 생긴 것은 뺀다', { timeout: SCAN_TIMEOUT_MS }, () => {
    const defined = definedClasses()
    const stale = [...Object.keys(NO_STYLE), ...Object.keys(UNSTYLED_TODO)].filter((cls) =>
      defined.has(cls),
    )
    expect(stale, `규칙이 생겼으니 목록에서 빼세요: ${stale.join(', ')}`).toEqual([])
  })

  it('마크업에서 사라진 이름을 목록이 들고 있지 않다', { timeout: SCAN_TIMEOUT_MS }, () => {
    /* 클래스가 지워졌는데 목록에 남으면, 다음 사람이 없는 것을 근거로 삼는다. */
    const used = new Set(classesUsedInMarkup().keys())
    const gone = [...Object.keys(NO_STYLE), ...Object.keys(UNSTYLED_TODO)].filter(
      (cls) => !used.has(cls),
    )
    expect(gone, `마크업에 없는 이름이다: ${gone.join(', ')}`).toEqual([])
  })
})

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
