/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import blueLogRaw from '../design/tokens/BlueLog.tokens.json?raw'
import lightRaw from '../design/tokens/Light.tokens.json?raw'
import darkRaw from '../design/tokens/Dark.tokens.json?raw'

/**
 * 토큰 동기화 가드.
 *
 * `src/styles/tokens.generated.css`는 `src/design/tokens/*.json`에서 생성한다
 * (`npm run build:tokens`). **JSON만 고치고 생성을 잊으면 화면은 옛 색을 쓰면서
 * 아무도 모른다** — 빌드도 테스트도 통과하기 때문이다.
 *
 * 그래서 값 대조를 테스트로 고정한다. `TEST_PLAN` 동기화 가드와 같은 취지다:
 * **드리프트에 신호를 붙인다.**
 *
 * JSON은 `?raw`로 읽지만 **CSS는 `node:fs`로 읽는다** — vitest는 CSS 처리를 끄고
 * 있어(`test.css` 기본값) `?raw`를 붙여도 빈 문자열이 돌아온다. 조용히 빈 값이
 * 들어오면 이 가드가 아무것도 검사하지 않게 되므로 파일을 직접 읽는다.
 * 타입 참조는 이 파일에만 붙여, 앱 코드에는 node 전역이 노출되지 않게 한다.
 */

interface FlatToken {
  value: unknown
  type?: string
}

function flatten(
  node: Record<string, unknown>,
  path: string[] = [],
  out: Record<string, FlatToken> = {},
): Record<string, FlatToken> {
  for (const [key, value] of Object.entries(node)) {
    if (key.startsWith('$')) continue
    if (value && typeof value === 'object' && '$value' in value) {
      const token = value as Record<string, unknown>
      out[[...path, key].join('.')] = {
        value: token.$value,
        type: token.$type as string | undefined,
      }
    } else if (value && typeof value === 'object') {
      flatten(value as Record<string, unknown>, [...path, key], out)
    }
  }
  return out
}

/** CSS 주석을 걷어낸다 — 규칙 검사가 설명 문장에 걸리지 않게 한다. */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 별칭 계층. 생성물이 아니라 손으로 쓰는 파일이며 fallback 체인이 여기 있다. */
const aliasCss = readFileSync(
  new URL('./tokens.css', import.meta.url),
  'utf-8',
)

const css = readFileSync(
  new URL('./tokens.generated.css', import.meta.url),
  'utf8',
)

const parse = (raw: string) => flatten(JSON.parse(raw) as Record<string, unknown>)

const primitives = parse(blueLogRaw)
const light = parse(lightRaw)
const dark = parse(darkRaw)

/** `cii.a.fill` → `--cii-a-fill` */
const cssName = (path: string) => `--${path.replace(/\./g, '-')}`

const hexOf = (token: FlatToken) =>
  (token.value as { hex?: string }).hex?.toLowerCase()

/** 지정한 선택자 블록의 본문만 떼어낸다. */
function blockAfter(marker: string): string {
  const start = css.indexOf(marker)
  expect(start, `${marker} 블록이 생성물에 없습니다`).toBeGreaterThan(-1)
  const open = css.indexOf('{', start)
  const end = css.indexOf('\n}', open)
  return css.slice(open, end)
}

const rootBlock = blockAfter('\n:root {')
const darkBlock = blockAfter(":root[data-theme='dark'] {")

const REGENERATE = '`npm run build:tokens`를 실행하십시오.'

describe('디자인 토큰 — JSON과 생성 CSS가 일치한다', () => {
  it('라이트 색 토큰이 :root에 모두 있다', () => {
    const mismatched = Object.entries(light)
      .filter(([path, token]) => !rootBlock.includes(`${cssName(path)}: ${hexOf(token)};`))
      .map(([path, token]) => `${cssName(path)}: ${hexOf(token)}`)

    expect(
      mismatched,
      `Light.tokens.json과 tokens.generated.css가 어긋납니다. ${REGENERATE}`,
    ).toEqual([])
  })

  it('다크 색 토큰이 [data-theme=dark]에 모두 있다', () => {
    const mismatched = Object.entries(dark)
      .filter(([path, token]) => !darkBlock.includes(`${cssName(path)}: ${hexOf(token)};`))
      .map(([path, token]) => `${cssName(path)}: ${hexOf(token)}`)

    expect(
      mismatched,
      `Dark.tokens.json과 tokens.generated.css가 어긋납니다. ${REGENERATE}`,
    ).toEqual([])
  })

  it('두 테마의 색 토큰 키 집합이 같다', () => {
    // 한쪽에만 있으면 그 테마에서 정의되지 않은 색이 생겨 화면이 깨진다.
    expect(Object.keys(light).sort()).toEqual(Object.keys(dark).sort())
  })

  it('치수 토큰(spacing·radius·target·icon)이 생성물에 있다', () => {
    const missing = Object.keys(primitives).filter(
      (path) => !css.includes(`${cssName(path)}:`),
    )
    expect(missing, `누락된 치수 토큰: ${missing.join(', ')}. ${REGENERATE}`).toEqual([])
  })

  it('생성물을 직접 고치지 말라는 경고가 남아 있다', () => {
    expect(css).toContain('이 파일은 생성물이다')
  })
})

describe('테마 규칙 — 3-상태', () => {
  it('명시적 라이트 선택이 OS 다크를 이긴다', () => {
    expect(css).toContain('@media (prefers-color-scheme: dark)')
    expect(css).toContain(":root:not([data-theme='light'])")
  })

  it('라이트 팔레트가 속성 없는 기본 :root에 있다', () => {
    /*
     * 색을 미디어 쿼리나 [data-theme] 안에서만 정의하면, 속성이 없는 기본 상태에서
     * 그 색이 적용되지 않아 한쪽 테마의 글자가 다른 테마의 바탕 위에 얹힌다.
     */
    const missing = Object.keys(light).filter(
      (path) => !rootBlock.includes(`${cssName(path)}:`),
    )
    expect(missing, `기본 :root에 없는 색 토큰: ${missing.join(', ')}`).toEqual([])
  })
})

describe('폰트 fallback — DESIGN_SYSTEM §3 (#485)', () => {
  it('지정 폰트는 생성 토큰에서 온다 — 별칭이 이름을 다시 적지 않는다', () => {
    expect(css).toContain("--fontFamilies-sans: 'Noto Sans KR'")
    expect(aliasCss).toContain('--font-sans: var(--fontFamilies-sans)')
  })

  it('fallback 체인이 §3이 정한 그대로다', () => {
    /*
     * §3 원문 — 「**Noto Sans KR** (한글 우선) → fallback
     * `system-ui, "Malgun Gothic", sans-serif`」.
     */
    expect(aliasCss).toContain(
      "--font-sans: var(--fontFamilies-sans), system-ui, 'Malgun Gothic', sans-serif;",
    )
  })

  it('선언부에 Pretendard가 남아 있지 않다', () => {
    /*
     * v1.2까지의 지정 폰트다. §3이 「팀 환경 확보 문제로 교체했다」로 적으며
     * v2.0에서 걷어냈는데 체인에 남아 있으면, **Noto Sans KR이 없고 Pretendard가
     * 설치된 장비에서 구 폰트로 렌더된다** — 교체 자체가 무효가 된다.
     *
     * **주석은 보지 않는다.** 왜 걷어냈는지를 파일에 적어 두는 것이 이 규칙을
     * 되돌리지 않게 하는 근거인데, 원문 전체를 훑으면 그 설명 자체가 실패가 된다.
     */
    const declarations = stripComments(aliasCss) + stripComments(css)
    expect(declarations).not.toContain('Pretendard')
  })
})

/**
 * 문자로 쓰는 시맨틱 색의 대비 가드 — `DESIGN_SYSTEM §0.2` 제약 1 (`#485`).
 *
 * ## 왜 값을 눈으로 보지 않고 계산하는가
 *
 * `--color-danger`(#e53e3e)는 라이트에서 **4.13:1**, `--color-warning`(#d97b14)은
 * **3.09:1**이다. 둘 다 4.5:1에 못 미치는데 **화면이 깨지지 않아** 오래 남아 있었다.
 * 다크에서는 통과하므로 다크 모드 검수로도 드러나지 않았다.
 *
 * 그래서 문자 전용 별칭(`--color-*-text`)을 두었고, **그 값이 실제로 통과하는지를
 * 계산으로 건다.** 나중에 누가 「시맨틱 색으로 되돌리자」며 값을 바꾸면 여기서 걸린다.
 */
function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const linear = channels.map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('문자용 시맨틱 색 대비 — §0.2 제약 1 (#485)', () => {
  /** 라이트 `--surface-card`. 오류 문구·배지가 얹히는 바탕이다. */
  const LIGHT_SURFACE = '#ffffff'

  const declared = (name: string): string => {
    // 별칭은 `tokens.css`에 있다 — 생성물(`css`)이 아니라 `aliasCss`를 본다.
    const found = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(aliasCss)
    expect(found, `${name}이 tokens.css에 hex로 선언돼 있지 않다`).not.toBeNull()
    return (found as RegExpExecArray)[1].toLowerCase()
  }

  it('--color-danger-text가 흰 바탕에서 4.5:1을 넘는다', () => {
    const value = declared('--color-danger-text')
    expect(contrast(value, LIGHT_SURFACE)).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-warning-text가 흰 바탕에서 4.5:1을 넘는다', () => {
    const value = declared('--color-warning-text')
    expect(contrast(value, LIGHT_SURFACE)).toBeGreaterThanOrEqual(4.5)
  })

  /*
   * 종전 값을 그대로 다시 넣는 것을 막는다. 「시맨틱 토큰이 있는데 왜 별칭을
   * 쓰나」는 합리적인 의문이고, 답은 **그 값이 문자로 쓸 수 없다**는 것이다.
   */
  it('생성 토큰의 Danger·Warning은 문자로 쓰기에 모자란다 — 별칭이 필요한 이유', () => {
    expect(contrast('#e53e3e', LIGHT_SURFACE)).toBeLessThan(4.5)
    expect(contrast('#d97b14', LIGHT_SURFACE)).toBeLessThan(4.5)
  })
})

/**
 * 중립 면 위의 대비 — `DESIGN_SYSTEM §0.2` 제약 1 · `§2.2`.
 *
 * ## 왜 면(surface)에 가드를 거는가
 *
 * 종전 가드는 **문자색만** 봤다. 그런데 대비는 두 값의 관계이고, 지금까지
 * **바닥이 움직이지 않는다고 가정**하고 있었다.
 *
 * 그 가정이 실제로 깨졌다. `#699`가 `--text-faint`를 문자에서 걷어내면서
 * 면적·비활성에는 남겼고 그 근거가 **「비텍스트 3:1을 넘는다」**였는데, 그 근거는
 * 면 값에 매달려 있다. 라이트 중립이 `§2.2` 쿨톤으로 정렬될 때 `--surface-inset`
 * 위 값이 **3.26 → 3.08**로 내려왔다. 통과하지만 **여섯 조합 중 가장 빠듯한
 * 자리**이고, 면을 한 단만 더 어둡게 잡으면 여기가 먼저 깨진다.
 *
 * 그때 깨지는 것은 색이 아니라 **`#699`가 남긴 예외 세 자리의 정당성**이다.
 * 화면은 멀쩡히 그려지므로 눈으로는 잡히지 않는다 — `#620`·`#699`가 겪은 것과
 * 같은 형태다.
 *
 * ## 무엇을 거는가
 *
 * 세 면 × 두 테마 × 세 문자 토큰. `§16 항목 3`(중립색 팔레트)이 열려 있어
 * **이 값들은 앞으로도 움직인다.** 움직여도 좋되, 기준을 밟으면 여기서 멈춘다.
 */
describe('중립 면 위 대비 — §2.2 · §16 항목 3', () => {
  const SURFACES = ['surface.card', 'surface.page', 'surface.inset'] as const

  /** `--text-muted`는 문서의 `text-faint`다 — 위 블록의 경고 참조. */
  const ROLES = [
    { key: 'text.primary', label: '본문', min: 4.5, basis: '§0.2 제약 1' },
    { key: 'text.secondary', label: '보조 문자', min: 4.5, basis: '§0.2 제약 1' },
    { key: 'text.muted', label: 'faint(면적·비활성)', min: 3, basis: '비텍스트 3:1' },
  ] as const

  const THEMES = [
    ['라이트', light],
    ['다크', dark],
  ] as const

  for (const [themeName, tokens] of THEMES) {
    for (const surface of SURFACES) {
      for (const role of ROLES) {
        it(`${themeName} — ${role.label}가 ${surface} 위에서 ${role.min}:1을 넘는다 (${role.basis})`, () => {
          const bg = hexOf(tokens[surface])
          const fg = hexOf(tokens[role.key])
          expect(bg, `${surface}가 ${themeName} 토큰에 없습니다`).toBeTruthy()
          expect(fg, `${role.key}가 ${themeName} 토큰에 없습니다`).toBeTruthy()
          expect(contrast(fg as string, bg as string)).toBeGreaterThanOrEqual(role.min)
        })
      }
    }
  }

  /*
   * 면과 카드가 **구분돼 보이는지**는 대비비로 잴 수 없다. 색상(hue)차가 명도차를
   * 대신하기 때문이다 — 웜 `#f2f2ef`는 흰 카드와 명도비 1.12로 쿨 `#f4f6f9`(1.08)
   * 보다 큰데도 더 밋밋하게 읽혔다. 그래서 여기서는 **명도가 아니라 「페이지가
   * 카드와 다른 값이다」**만 건다. 같아지면 카드가 사라진다.
   */
  it('페이지 배경과 카드 면이 같은 값이 아니다', () => {
    for (const [themeName, tokens] of THEMES) {
      expect(
        hexOf(tokens['surface.page']),
        `${themeName}에서 페이지와 카드가 같은 값이면 카드가 면으로 보이지 않는다`,
      ).not.toBe(hexOf(tokens['surface.card']))
    }
  })
})

describe('시맨틱 색을 문자색으로 쓰지 않는다 — §0.2 제약 1 (#620)', () => {
  /**
   * `#485` ⑤가 문자 전용 별칭을 만들고 **두 곳만** 옮겼고, `#620`이 나머지 33곳을
   * 옮겼다. 이 가드는 **다시 들어오는 것**을 막는다 — 새 화면이 무심코
   * `color: var(--color-danger)`를 쓰면 라이트에서 4.13:1이 되는데, **화면이 깨지지
   * 않아** 그 상태가 오래 남는다(실제로 그랬다).
   *
   * **면적 색은 보지 않는다.** `background`·`border`는 비텍스트라 3:1이면 충분하고,
   * 문자 전용 별칭으로 바꾸면 면적이 어두워져 등급 색과 충돌한다.
   */
  const OFFENDERS = ['--semantic-danger', '--color-danger', '--color-warning']

  function cssFiles(dir: string): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules') continue
        out.push(...cssFiles(full))
      } else if (entry.name.endsWith('.css')) {
        out.push(full)
      }
    }
    return out
  }

  const HERE = fileURLToPath(new URL('.', import.meta.url))
  const files = cssFiles(join(HERE, '..'))

  it('훑을 CSS 파일을 실제로 찾았다', () => {
    // 수집이 깨지면 아래 대조가 전부 무의미해진다 — 그것부터 막는다.
    expect(files.length).toBeGreaterThanOrEqual(15)
  })

  it('color 선언에 시맨틱 원본 색이 없다', () => {
    // `border-color:`·`background-color:`는 앞에 `-`가 있어 걸리지 않는다.
    const pattern = new RegExp(
      `(?<![-\\w])color:\\s*var\\((${OFFENDERS.join('|')})\\)`,
    )
    const hits: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf-8')
        .split('\n')
        .forEach((line, i) => {
          if (pattern.test(line)) hits.push(`${file}:${i + 1}  ${line.trim()}`)
        })
    }
    expect(hits, `문자 전용 별칭(--color-*-text)으로 바꾸세요:\n${hits.join('\n')}`).toEqual(
      [],
    )
  })

  it('면적 색은 원본을 그대로 쓴다 — 바꾸면 등급 색과 충돌한다', () => {
    const area = new RegExp(
      `(background|border)[a-z-]*:\\s*[^;]*var\\((${OFFENDERS.join('|')})\\)`,
    )
    const kept = files.filter((f) => area.test(readFileSync(f, 'utf-8')))
    expect(kept.length).toBeGreaterThan(0)
  })
})

describe('faint 계열을 문자색으로 쓰지 않는다 — §2.2 · §16 항목 1 ⓐ', () => {
  /**
   * **이름이 같아 보이는 것이 다른 값이다.** 생성 토큰 `--text-muted`는 문서의
   * `text-muted`가 아니라 **`text-faint`**(`#8b8a83` / dark `#6b7686`)이며,
   * 라이트 3.08~3.46:1 · 다크 3.47~4.11:1로 **양쪽 모두 §0.2 제약 1(4.5:1) 미달**이다.
   *
   * 그런데 이 값을 문자색으로 쓰는 자리가 **53곳**이었다 — 대시보드·실시간 CII·
   * 선박 상세의 라벨과 캡션이 전부 여기 걸려 있었다. `#620`이 시맨틱 색에서 겪은 것과
   * 같은 형태다: **화면이 깨지지 않아** 아무도 못 잡는다.
   *
   * 이 가드는 다시 들어오는 것을 막는다. 값을 바꾸는 길(§16-1 ⓑ)로는 닫히지 않는다 —
   * `#647380`의 `4.86:1`은 흰 카드 위 값이고 `--surface-inset` 위에서는 `4.34:1`이다.
   *
   * ## 허용하는 자리 둘 — 문자가 아니다
   *
   * ⑴ **면적** — `background`는 아예 보지 않는다. 비텍스트 3:1 기준이다
   * ⑵ **비활성** — `:disabled` · `--disabled`. WCAG 1.4.3이 비활성 요소를 제외한다
   *
   * 아이콘 두 개(`--color`가 `stroke: currentcolor`로 흘러가는 자리)는 문자가 아니라
   * 그래픽이므로 이름으로 예외를 둔다. **선택자를 적어 두면 새 자리가 조용히
   * 늘어나지 않는다** — 늘리려면 이 목록을 고쳐야 하고, 그건 리뷰에 걸린다.
   */
  const FAINT = ['--color-text-faint', '--text-muted']
  const ICON_EXCEPTIONS = ['.app-shell__util-icon', '.app-shell__iconbtn', '.history__swatch']

  // 위 describe의 수집기는 그 블록 안에 갇혀 있다. 같은 규칙으로 다시 모은다.
  function collect(dir: string): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules') continue
        out.push(...collect(full))
      } else if (entry.name.endsWith('.css')) {
        out.push(full)
      }
    }
    return out
  }

  const HERE = fileURLToPath(new URL('.', import.meta.url))
  const files = collect(join(HERE, '..'))

  it('훑을 CSS 파일을 실제로 찾았다', () => {
    expect(files.length).toBeGreaterThanOrEqual(15)
  })

  function faintTextHits(file: string): string[] {
    const hits: string[] = []
    let selector = ''
    let pending: string[] = []
    readFileSync(file, 'utf-8')
      .split('\n')
      .forEach((raw, i) => {
        const line = raw.trim()
        if (line.endsWith('{')) {
          pending.push(line.slice(0, -1).trim())
          selector = pending.join(' ')
          pending = []
        } else if (line.endsWith(',') && !line.startsWith('/') && !line.includes(':')) {
          pending.push(line)
        }
        const decl = /^(color|fill)\s*:\s*var\((--color-text-faint|--text-muted)\)\s*;/.exec(line)
        if (!decl) return
        if (/:disabled|--disabled/.test(selector)) return
        if (ICON_EXCEPTIONS.some((s) => selector.includes(s))) return
        hits.push(`${file}:${i + 1}  ${selector} { ${line} }`)
      })
    return hits
  }

  it('color·fill 선언에 faint 계열이 없다 (비활성·아이콘 제외)', () => {
    const hits = files.flatMap(faintTextHits)
    expect(
      hits,
      `라벨·캡션·힌트는 --color-text-muted(=--text-secondary, 6.49:1)를 씁니다:\n${hits.join('\n')}`,
    ).toEqual([])
  })

  it('토큰 자체는 남아 있다 — 면적·비활성이 쓴다', () => {
    const tokens = readFileSync(join(HERE, 'tokens.css'), 'utf-8')
    expect(tokens).toContain('--color-text-faint:')
    const used = files.some((f) =>
      FAINT.some((t) => new RegExp(`background[a-z-]*:\\s*var\\(${t}\\)`).test(readFileSync(f, 'utf-8'))),
    )
    expect(used).toBe(true)
  })
})

/**
 * Primary 채움면 위 글자 대비 — `DESIGN_SYSTEM §0.2` 제약 1 (`#717`).
 *
 * ## 종전 가드가 못 보던 자리
 *
 * 위 두 가드는 **문자색 × 중립 면**만 본다. 그런데 `§8`이 정의한 Primary 버튼은
 * 글자가 **브랜드색 면 위**에 얹힌다. 그 조합은 어느 가드에도 걸리지 않았고,
 * 실제로 **아바타가 다크에서 3.76:1**인 채로 남아 있었다.
 *
 * ## `color-mix`를 계산한다
 *
 * 채움면은 다크에서 `color-mix(in srgb, var(--semantic-primary) 70%, var(--surface-page))`다.
 * hex가 아니므로 위쪽 `declared()`처럼 정규식으로 뽑아 쓸 수 없다 — **여기서 직접
 * 계산한다.** 계산하지 않으면 이 자리는 「선언돼 있다」까지만 확인되고 **값이 맞는지는
 * 아무도 안 보는 상태**로 되돌아간다.
 *
 * 지원하는 문법은 이 파일이 실제로 쓰는 두 가지뿐이다 — `var(--x)`와
 * `color-mix(in srgb, <색> N%, <색>)`. 더 넓히지 않는다. CSS 파서를 만드는 것이
 * 목적이 아니라 **세 값이 4.5:1을 넘는지**를 잠그는 것이 목적이다.
 */
describe('Primary 채움면 위 글자 대비 — §0.2 제약 1 (#717)', () => {
  /** `cii.a.fill` 꼴 경로를 CSS 이름으로 바꿔 hex를 찾는 표. */
  const hexTable = (theme: Record<string, FlatToken>): Record<string, string> =>
    Object.fromEntries(
      Object.entries(theme)
        .map(([path, token]) => [cssName(path), hexOf(token)])
        .filter(([, hex]) => typeof hex === 'string'),
    ) as Record<string, string>

  /** 별칭 파일의 한 블록에서 `--name: value;` 를 전부 걷는다. */
  function declarationsIn(marker: string): Record<string, string> {
    const start = aliasCss.indexOf(marker)
    expect(start, `${marker} 블록이 tokens.css에 없습니다`).toBeGreaterThan(-1)
    const body = stripComments(aliasCss.slice(start + marker.length))
    const end = body.indexOf('\n}')
    const found: Record<string, string> = {}
    for (const [, name, value] of body
      .slice(0, end)
      .matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
      found[name] = value.trim()
    }
    return found
  }

  const lightAlias = declarationsIn('\n:root {')
  const darkAlias = {
    ...lightAlias,
    ...declarationsIn("\n:root[data-theme='dark'] {"),
  }

  function mix(a: string, b: string, percent: number): string {
    const at = percent / 100
    const channel = (i: number) =>
      Math.round(
        parseInt(a.slice(i, i + 2), 16) * at + parseInt(b.slice(i, i + 2), 16) * (1 - at),
      )
    return `#${[1, 3, 5].map((i) => channel(i).toString(16).padStart(2, '0')).join('')}`
  }

  function evaluate(expression: string, generated: Record<string, string>, alias: Record<string, string>): string {
    const value = expression.trim()

    if (/^#[0-9a-fA-F]{6}$/.test(value)) return value.toLowerCase()

    const variable = /^var\((--[\w-]+)\)$/.exec(value)
    if (variable) {
      const name = variable[1]
      const resolved = generated[name] ?? alias[name]
      expect(resolved, `${name}을 찾지 못했습니다`).toBeDefined()
      return evaluate(resolved as string, generated, alias)
    }

    const mixed = /^color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+)\)$/.exec(value)
    if (mixed) {
      return mix(
        evaluate(mixed[1], generated, alias),
        evaluate(mixed[3], generated, alias),
        Number(mixed[2]),
      )
    }

    throw new Error(`지원하지 않는 색 표현입니다: ${value}`)
  }

  const THEMES = [
    { name: '라이트', generated: hexTable(light), alias: lightAlias },
    { name: '다크', generated: hexTable(dark), alias: darkAlias },
  ]

  it.each(THEMES)('$name — 채움면 위 글자가 4.5:1 이상이다', ({ generated, alias }) => {
    const fill = evaluate(alias['--color-primary-solid'], generated, alias)
    const hover = evaluate(alias['--color-primary-solid-hover'], generated, alias)
    const text = evaluate(alias['--color-on-primary'], generated, alias)

    expect(contrast(text, fill)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(text, hover)).toBeGreaterThanOrEqual(4.5)
  })

  it('두 다크 블록이 같은 값을 선언한다 — 한쪽만 고치면 OS 다크와 명시 다크가 갈린다', () => {
    const media = declarationsIn("\n  :root:not([data-theme='light']) {")
    for (const name of [
      '--color-primary-solid',
      '--color-primary-solid-hover',
      '--color-on-primary',
    ]) {
      expect(media[name], `@media 블록에 ${name}이 없습니다`).toBe(
        declarationsIn("\n:root[data-theme='dark'] {")[name],
      )
    }
  })

  /*
   * 되돌림 방지 — 「`--color-primary`를 그냥 쓰면 되지 않나」로 돌아가는 것을 막는다.
   * 그 조합이 실제로 미달이라는 사실을 여기 숫자로 남긴다.
   */
  it('다크 --semantic-primary 위에는 쓸 만한 문자색이 없다', () => {
    const g = hexTable(dark)
    for (const name of ['--surface-card', '--text-primary']) {
      expect(contrast(g[name], g['--semantic-primary'])).toBeLessThan(4.5)
    }
    expect(contrast('#ffffff', g['--semantic-primary'])).toBeLessThan(4.5)
  })
})
