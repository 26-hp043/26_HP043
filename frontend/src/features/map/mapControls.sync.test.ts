import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 지도 컨트롤 묶음의 면이 테마를 따른다 (#2430).
 *
 * ## 무엇을 막는가
 *
 * 「지구본」 버튼의 글자는 `--text-primary`다(`DESIGN_SYSTEM §9.5` 〔확정〕 ·
 * `projectionToggle.sync.test.ts`). 그 글자가 얹힌 **면**은 MapLibre 기본 CSS가 흰색으로
 * 박아 두어 다크에서 밝은 글자 · 흰 면(1.22:1)이 됐다. 면을 토큰으로 옮긴 규칙이 사라지거나
 * 리터럴 색으로 돌아가면 같은 결함이 다시 난다.
 */
const CSS = readFileSync(join(process.cwd(), 'src/features/map/mapControls.css'), 'utf-8')
/** 설명 문장이 근거가 되지 않게 주석을 걷는다. */
const code = CSS.replace(/\/\*[\s\S]*?\*\//g, '')
const RENDERER = readFileSync(join(process.cwd(), 'src/features/map/mapLibreRenderer.ts'), 'utf-8')

describe('지도 컨트롤 묶음의 면이 테마를 따른다 (#2430)', () => {
  it('묶음의 면은 카드 면 토큰이다 — 글자(--text-primary)와 같은 테마를 탄다', () => {
    expect(code).toMatch(/\.maplibregl-ctrl-group\s*\{[^}]*background:\s*var\(--surface-card\)/)
  })

  it('MapLibre 기본 규칙을 이긴다 — 선택자가 지도 컨테이너에서 시작한다', () => {
    // 기본 규칙은 `.maplibregl-ctrl-group` 하나라, 같은 무게면 불러오는 순서에 결과가 걸린다.
    expect(code).toMatch(/\.maplibregl-map\s+\.maplibregl-ctrl-group\s*\{/)
  })

  it('다크에서 아이콘 그림을 뒤집는다 — 토큰과 같은 두 갈래 모두', () => {
    const invert = /\.maplibregl-ctrl-icon\s*\{[^}]*filter:\s*invert\(1\)/
    const explicit = code.slice(code.indexOf(":root[data-theme='dark']"))
    const system = code.slice(code.indexOf(":root:not([data-theme='light'])"))
    expect(code).toContain('(prefers-color-scheme: dark)')
    expect(explicit).toMatch(invert)
    expect(system).toMatch(invert)
  })

  it('새 색을 만들지 않았다 — 리터럴 색이 없다 (§0.2)', () => {
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(code).not.toMatch(/\brgba?\(/)
  })

  it('지도 렌더러가 MapLibre 기본 CSS 뒤에 이 파일을 불러온다', () => {
    const base = RENDERER.indexOf("import 'maplibre-gl/dist/maplibre-gl.css'")
    const ours = RENDERER.indexOf("import './mapControls.css'")
    expect(base).toBeGreaterThanOrEqual(0)
    expect(ours).toBeGreaterThan(base)
  })
})
