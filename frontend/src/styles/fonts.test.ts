// 지정 서체가 저장소 안에 실제로 있는지 — `#925` · `DESIGN_SYSTEM §3`
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = join(HERE, '..', '..')
const css = readFileSync(join(HERE, 'fonts.css'), 'utf-8')
/** 규칙 검사가 설명 문장에 걸리지 않게 한다 — `#831`·`#829`·`#694`에서 세 번 밟았다. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')

/** `§3`이 쓰는 두 서체 × 두 굵기. */
const EXPECTED = [
  ['Noto Sans KR', 400, 'noto-sans-kr-400.woff2'],
  ['Noto Sans KR', 500, 'noto-sans-kr-500.woff2'],
  ['Noto Sans Mono', 400, 'noto-sans-mono-400.woff2'],
  ['Noto Sans Mono', 500, 'noto-sans-mono-500.woff2'],
] as const

describe('지정 서체 자체 호스팅 — #925', () => {
  it.each(EXPECTED)('%s %d — 선언이 있고 파일이 실재한다', (family, weight, file) => {
    /*
     * **이 검사가 이 파일의 핵심이다.** 종전에는 토큰이 `Noto Sans KR`을 가리키는데
     * **가리키는 파일이 없었다.** 폰트가 깔린 PC에서는 OS가 대신 그려 주므로
     * 아무도 알아채지 못했고, 드러나는 자리는 외부로 나가는 화면이었다.
     */
    /*
     * `@font-face` 블록으로 잘라서 본다. 이름만으로 찾으면 **같은 서체의 첫 블록**만
     * 잡혀 400과 500이 구분되지 않는다.
     */
    const declaration = rules
      .split('@font-face')
      .slice(1)
      .find((b) => b.includes(`font-family: '${family}'`) && b.includes(`font-weight: ${weight};`))

    expect(declaration, `${family} ${weight} 블록을 찾지 못했습니다`).toBeDefined()
    expect(declaration, `${family} ${weight}가 다른 파일을 가리킵니다`).toContain(file)

    const path = join(ROOT, 'public', 'fonts', file)
    expect(existsSync(path), `${file}이 저장소에 없습니다`).toBe(true)
    // 빈 파일이나 받다 만 파일을 「있다」로 세지 않는다.
    expect(statSync(path).size).toBeGreaterThan(10_000)
  })

  it('네 선언 모두 굵기와 swap이 명시돼 있다', () => {
    for (const [, weight] of EXPECTED) {
      expect(rules).toContain(`font-weight: ${weight};`)
    }
    // `swap`이 없으면 폰트를 기다리는 동안 글자가 통째로 감춰진다.
    expect(rules.match(/font-display:\s*swap/g)).toHaveLength(EXPECTED.length)
  })

  it('CDN에서 불러오지 않는다 — #791', () => {
    /*
     * `#791`이 「인터넷이 없다고 가정한 경로가 반드시 함께 있어야 한다」로 못 박는다.
     * 링크로 바꾸면 인터넷 없는 시연에서 폰트가 다시 빠진다.
     */
    expect(rules).not.toMatch(/https?:\/\//)
    for (const [, , file] of EXPECTED) {
      expect(rules).toContain(`url('/fonts/${file}')`)
    }
  })

  it('라이선스 파일을 함께 둔다 — OFL', () => {
    const ofl = join(ROOT, 'public', 'fonts', 'OFL.txt')
    expect(existsSync(ofl), 'OFL.txt가 없습니다').toBe(true)
    expect(readFileSync(ofl, 'utf-8')).toContain('SIL Open Font License')
  })

  it('생성 절차가 저장소에 남아 있다', () => {
    /*
     * 파일만 넣고 만드는 방법을 적어 두지 않으면 **다시 만들 수 없다.**
     * 굵기가 바뀌거나 서브셋 범위를 넓혀야 할 때 그 스크립트를 고쳐 다시 돌린다.
     */
    const script = join(ROOT, '..', 'scripts', 'build_fonts.py')
    expect(existsSync(script), 'scripts/build_fonts.py가 없습니다').toBe(true)
    const body = readFileSync(script, 'utf-8')
    expect(body).toContain('WEIGHTS = (400, 500)')
  })
})
