import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * **아이콘 규격값의 출처는 Figma 하나다** — `DESIGN_SYSTEM §12` · `§15` (`#1174`).
 *
 * ## 무엇이 갈려 있었나
 *
 * 같은 규격이 **두 곳**에 있었다. 커스텀 아이콘(`NavIcons.tsx`)은 CSS로 생성 토큰을
 * 읽는데, 세트 아이콘(`Icon.tsx`)은 같은 값을 코드에 적었다 — `size = 20` ·
 * `strokeWidth={1.5}`, 그리고 호출부 13곳의 `size={16}`.
 *
 * 디자이너가 Figma에서 `icon/stroke`를 `1.6`으로 바꾸면 **사이드바만 굵어지고
 * 나머지는 그대로**가 된다. 지금 깨지지 않는 이유는 두 경로의 값이 **우연히 같기**
 * 때문이고, 그래서 오래 남는다 — `#620`의 문자색 미달이 간 경로다.
 *
 * ## 이 검사가 보는 것
 *
 * `digits.sync.test.ts`·`units.sync.test.ts`와 같은 규율이다. **정본(생성 토큰)과
 * 코드가 어긋나면 실패한다.** 값을 비교하지 않고 **이름의 집합**을 비교하는 것이
 * 요점이다 — 값을 적어 두면 이 파일이 세 번째 출처가 된다.
 */
const SRC = join(new URL('.', import.meta.url).pathname, '..')

const ICON_TSX = readFileSync(join(SRC, 'components/Icon.tsx'), 'utf8')
const ICON_CSS = readFileSync(join(SRC, 'components/Icon.css'), 'utf8')
const GENERATED = readFileSync(join(SRC, 'styles/tokens.generated.css'), 'utf8')

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : tsxFiles(path)
    if (!/\.tsx$/.test(name)) return []
    return [path]
  })
}

/** 생성 토큰이 가진 크기 이름. `--icon-stroke`는 크기가 아니라 제외한다. */
function generatedSizeNames(): string[] {
  const found = new Set<string>()
  for (const [, name] of GENERATED.matchAll(/--icon-([a-z-]+):/g)) {
    if (name !== 'stroke') found.add(name)
  }
  return [...found].sort()
}

describe('아이콘 규격 동기 — §12 · §15 (#1174)', () => {
  it('생성 토큰에 크기 셋과 두께가 있다', () => {
    // 이 검사가 헛돌지 않게 먼저 잠근다 — 토큰이 사라지면 아래가 전부 공집합 비교가 된다.
    expect(generatedSizeNames().length).toBeGreaterThan(0)
    expect(GENERATED).toMatch(/--icon-stroke:/)
  })

  it('Icon.tsx가 규격값을 숫자로 갖지 않는다', () => {
    /*
     * `strokeWidth`는 **속성 자체가 없어야** 한다 — 값이 무엇이든 코드가 두께를
     * 정하는 순간 출처가 둘이 된다. `size`는 이름을 받으므로 기본값도 이름이다.
     */
    const code = ICON_TSX.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
    expect(code, 'strokeWidth를 코드가 정하고 있다 — Icon.css가 토큰으로 먹인다').not.toMatch(
      /strokeWidth\s*[=:]/,
    )
    expect(code, 'size 기본값이 숫자다 — 이름이어야 한다').not.toMatch(/size\s*=\s*\d/)
  })

  it('Icon.css가 크기·두께를 전부 토큰에서 읽는다', () => {
    expect(ICON_CSS).toMatch(/stroke-width:\s*var\(--icon-stroke\)/)
    for (const name of generatedSizeNames()) {
      expect(ICON_CSS, `.icon--${name}이 없다`).toMatch(
        new RegExp(`\\.icon--${name}\\s*\\{[^}]*var\\(--icon-${name}\\)`),
      )
    }
  })

  it('size가 받는 이름이 생성 토큰의 크기 이름과 정확히 같다', () => {
    /*
     * **값이 아니라 이름을 맞춘다.** Figma에 크기가 하나 늘면 유니온이 낡고, 하나
     * 줄면 코드가 없는 토큰을 가리킨다 — 둘 다 여기서 드러난다.
     */
    const union = /size\?:\s*([^\n]+)/.exec(ICON_TSX)
    expect(union, 'size 유니온을 읽지 못했습니다').not.toBeNull()
    const names = [...(union as RegExpExecArray)[1].matchAll(/'([a-z-]+)'/g)]
      .map(([, name]) => name)
      .sort()
    expect(names).toEqual(generatedSizeNames())
  })

  it('호출부가 크기를 숫자로 주지 않는다', () => {
    const offenders: string[] = []
    for (const path of tsxFiles(SRC)) {
      const text = readFileSync(path, 'utf8')
      for (const match of text.matchAll(/<Icon\b[\s\S]{0,200}?\/>/g)) {
        if (/size=\{[^}]*\d/.test(match[0])) {
          offenders.push(`${path.slice(SRC.length)} :: ${match[0].replace(/\s+/g, ' ')}`)
        }
      }
    }
    expect(offenders, '크기는 토큰 이름으로 준다 (§15 · #1174)').toEqual([])
  })
})
