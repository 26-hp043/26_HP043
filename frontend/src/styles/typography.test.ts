// `DESIGN_SYSTEM §3` 자간 — display 급 제목의 조임이 `h1` 한 곳에서 걸리는지 (#749)
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
/** 규칙 검사가 설명 문장에 걸리지 않게 한다 — `#831`·`#829`·`#694`에서 세 번 밟았다. */
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const globalRules = strip(readFileSync(join(HERE, 'global.css'), 'utf-8'))
const pageHeadRules = strip(
  readFileSync(join(HERE, '..', 'components', 'PageHeader.css'), 'utf-8'),
)

/** `selector { … }` 블록 하나의 본문. 선택자가 정확히 그것인 블록만 잡는다. */
function block(css: string, selector: string): string | undefined {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css)?.[2]
}

describe('§3 자간 — display 급 제목 (#749)', () => {
  it('h1이 조임을 건다 — 크기 토큰을 정하는 자리', () => {
    /*
     * `§3`은 화면이 아니라 **크기 토큰**에 자간을 건다. 종전에는 `PageHeader`의 제목에만
     * 있어 같은 display 크기인 선박 등록 제목은 조여지지 않았다.
     */
    const h1 = block(globalRules, 'h1')
    expect(h1, 'global.css에서 h1 블록을 찾지 못했습니다').toBeDefined()
    expect(h1).toContain('letter-spacing: var(--letterSpacing-tight)')
  })

  it('PageHeader 제목이 따로 들고 있지 않다 — 두 곳에 두면 한쪽만 고쳐진다', () => {
    const title = block(pageHeadRules, '.page-head__title')
    expect(title, 'PageHeader.css에서 .page-head__title 블록을 찾지 못했습니다').toBeDefined()
    expect(title).not.toContain('letter-spacing')
  })
})
