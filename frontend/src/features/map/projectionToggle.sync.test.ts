import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 지구본 ↔ 평면 전환 버튼의 모양 — `DESIGN_SYSTEM §9.5` 〔확정 2026-10-07 · `#2154`〕.
 *
 * ## 무엇을 막는가
 *
 * 이 버튼은 `§8`의 두 갈래(버튼 · 텍스트 버튼) **어느 쪽도 아니다** — 지도 위에서는
 * 글자만 둔 버튼이 바다·육지 어디에 놓이느냐에 따라 대비가 흔들리므로, 면과 테두리를
 * **지도 컨트롤 묶음(`maplibregl-ctrl-group`)에서 빌린다.** 확정이 그 예외를 「지도 위
 * 컨트롤에만」으로 좁혀 두었으니, 규칙이 그 자리에 실제로 닿는지를 여기서 본다.
 *
 * 글자는 `label`(13)이다. 종전 임시안은 `caption`(12)이었는데 `§3`에서 `caption`은
 * **보조 설명·단위·축 라벨**의 크기이고, 이 글자는 **누르는 것의 이름**이라 그 갈래가
 * 아니다. 값을 박지 않고 **토큰 이름**을 단언한다 — 값은 Figma 소관이다(`§0.2`).
 */
const CSS = readFileSync(join(process.cwd(), 'src/features/map/projectionToggle.css'), 'utf-8')
/** 설명 문장이 근거가 되지 않게 주석을 걷는다. */
const code = CSS.replace(/\/\*[\s\S]*?\*\//g, '')

/** 상태 가지(`:focus-visible` 등)가 아닌 **기본 규칙**의 선택자와 본문. */
function baseRule(selectorPart: string): { selector: string; body: string } {
  for (const [, selectors, body] of code.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (selectors.includes(selectorPart) && !selectors.includes(':')) {
      return { selector: selectors.trim(), body }
    }
  }
  throw new Error(`규칙을 찾지 못했습니다: ${selectorPart}`)
}

describe('지구본↔평면 버튼이 §9.5 확정과 같다 (#2154)', () => {
  const { selector, body } = baseRule('.bluelog-projection__toggle')

  it('규칙을 실제로 읽었다 — 파서가 조용히 빈 본문을 내지 않게', () => {
    expect(body.trim().length).toBeGreaterThan(40)
  })

  it('글자는 label이다 — caption이 아니다', () => {
    expect(body).toMatch(/font-size:\s*var\(--font-size-label\)/)
    expect(body).not.toMatch(/font-size:\s*var\(--font-size-caption\)/)
  })

  it('글자색은 --text-primary다', () => {
    expect(body).toMatch(/color:\s*var\(--text-primary\)/)
  })

  it('지도 컨트롤 묶음 안에 있다 — 면과 테두리를 거기서 빌린다', () => {
    /*
     * ⚠️ **기본 규칙의 선택자**를 본다 — 파일 어딘가에 그 글자가 있는지로 보면 안 된다.
     * 처음 쓴 검사가 그랬는데, 돌연변이로 기본 규칙에서 접두사를 떼어 봐도 `:focus-visible`
     * 규칙이 같은 접두사를 들고 있어 **초록이 났다.** 상자를 그리는 것은 기본 규칙이다.
     */
    expect(selector).toContain('.maplibregl-ctrl-group')
  })

  it('새 색을 만들지 않았다 — 리터럴 hex가 없다 (§0.2)', () => {
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
