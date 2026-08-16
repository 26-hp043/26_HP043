/**
 * 디자인 토큰(JSON) → CSS 커스텀 프로퍼티 생성기.
 *
 * ## 왜 스크립트로 만드는가
 *
 * `src/design/tokens/*.json`은 **디자인 담당이 Figma에서 내보낸 원본**이다.
 * `DESIGN_SYSTEM.md`가 *"토큰의 이름·의미·제약을 확정하고 값은 Figma가 소유"* 로
 * 규정하므로, 값을 사람이 CSS로 옮겨 적으면 **전사 오류가 조용히 들어온다.**
 * 색상만 76개라 눈으로 대조할 수 없다.
 *
 * 그래서 CSS를 손으로 쓰지 않고 JSON에서 생성한다. 생성물(`src/styles/tokens.css`)은
 * 저장소에 커밋한다 — 개발 서버 기동에 빌드 단계를 끼워 넣지 않기 위해서다.
 *
 * ## 동기화는 CI가 지킨다
 *
 * ```
 * npm run build:tokens && git diff --exit-code src/styles/tokens.css
 * ```
 *
 * JSON을 고치고 이 스크립트를 돌리지 않으면 CI가 실패한다. `TEST_PLAN` 동기화
 * 가드(`test_testplan_sync.py`)와 같은 방식이다 — **드리프트에 신호를 붙인다.**
 *
 * ## 사용
 *
 * ```
 * npm run build:tokens
 * ```
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const TOKENS_DIR = join(HERE, '..', 'src', 'design', 'tokens')
const OUTPUT = join(HERE, '..', 'src', 'styles', 'tokens.generated.css')

/** DTCG 토큰 트리를 `{'cii.a.fill': {value, type, description}}` 형태로 편다. */
function flatten(node, path = [], out = {}) {
  for (const [key, value] of Object.entries(node)) {
    if (key.startsWith('$')) continue
    if (value && typeof value === 'object' && '$value' in value) {
      out[[...path, key].join('.')] = {
        value: value.$value,
        type: value.$type,
        description: value.$description ?? '',
      }
    } else if (value && typeof value === 'object') {
      flatten(value, [...path, key], out)
    }
  }
  return out
}

/** `cii.a.fill` → `--cii-a-fill` */
const cssName = (path) => `--${path.replace(/\./g, '-')}`

/**
 * 토큰 값을 CSS 값 문자열로.
 *
 * 색상은 Figma가 `components`(0~1 실수)와 `hex`를 함께 내보낸다. **`hex`를 쓴다** —
 * 실수 성분을 다시 8비트로 반올림하면 원본과 1 차이가 나는 값이 생긴다.
 */
function cssValue(token) {
  if (token.type === 'color') {
    const hex = token.value?.hex
    if (typeof hex !== 'string') {
      throw new Error(`색상 토큰에 hex가 없습니다: ${JSON.stringify(token.value)}`)
    }
    return hex.toLowerCase()
  }
  if (token.type === 'number') {
    // letterSpacing은 소수, 나머지 치수는 정수 px. 단위 없는 값(grid.columns 등)과
    // px 값을 여기서 구분하지 않고 호출부에서 정한다.
    return token.value
  }
  return String(token.value)
}

/** px를 붙이지 않는 number 토큰 — 개수·배수라 단위가 없다. */
const UNITLESS = new Set([
  'grid.columns',
  'grid.split-primary',
  'grid.split-secondary',
  'fontWeights.regular',
  'fontWeights.medium',
])

function renderPrimitive(path, token) {
  const raw = cssValue(token)
  if (token.type === 'number') {
    if (UNITLESS.has(path)) return `${cssName(path)}: ${raw};`
    // letterSpacing은 Figma가 소수 px로 준다. 반올림하지 않고 그대로 둔다.
    const rounded = Number.isInteger(raw) ? raw : Number(raw.toFixed(2))
    return `${cssName(path)}: ${rounded}px;`
  }
  if (token.type === 'string') {
    return `${cssName(path)}: '${raw}';`
  }
  return `${cssName(path)}: ${raw};`
}

function block(entries, indent = '  ') {
  return entries.map((line) => indent + line).join('\n')
}

function groupComment(label) {
  return `\n${' '.repeat(2)}/* ── ${label} ${'─'.repeat(Math.max(0, 56 - label.length))} */`
}

// ── 읽기 ────────────────────────────────────────────────────────────────────
const read = (name) =>
  flatten(JSON.parse(readFileSync(join(TOKENS_DIR, name), 'utf8')))

const primitives = read('BlueLog.tokens.json')
const light = read('Light.tokens.json')
const dark = read('Dark.tokens.json')

// 두 테마의 키 집합이 어긋나면 한쪽 테마에서 정의되지 않는 색이 생긴다.
const lightKeys = Object.keys(light).sort()
const darkKeys = Object.keys(dark).sort()
if (lightKeys.join('|') !== darkKeys.join('|')) {
  const onlyLight = lightKeys.filter((k) => !darkKeys.includes(k))
  const onlyDark = darkKeys.filter((k) => !lightKeys.includes(k))
  throw new Error(
    `Light/Dark 토큰 키가 다릅니다.\n  Light에만: ${onlyLight.join(', ') || '(없음)'}\n  Dark에만: ${onlyDark.join(', ') || '(없음)'}`,
  )
}

// ── 조립 ────────────────────────────────────────────────────────────────────
const primitiveGroups = [
  ['간격 (spacing)', 'spacing.'],
  ['모서리 (radius)', 'radius.'],
  ['선 두께 (borderWidth)', 'borderWidth.'],
  ['그리드 (grid)', 'grid.'],
  ['터치 타깃 (target)', 'target.'],
  ['아이콘 (icon)', 'icon.'],
  ['타이포 (fontFamilies · fontWeights · letterSpacing)', 'fontFamilies.'],
]

const primitiveLines = []
for (const [label, prefix] of primitiveGroups) {
  const keys = Object.keys(primitives).filter((k) => k.startsWith(prefix))
  if (!keys.length) continue
  primitiveLines.push(groupComment(label).trimStart())
  for (const k of keys) primitiveLines.push(renderPrimitive(k, primitives[k]))
  if (prefix === 'fontFamilies.') {
    for (const k of Object.keys(primitives).filter(
      (x) => x.startsWith('fontWeights.') || x.startsWith('letterSpacing.'),
    )) {
      primitiveLines.push(renderPrimitive(k, primitives[k]))
    }
  }
}

const colorLines = (theme) =>
  Object.keys(theme).map((k) => `${cssName(k)}: ${cssValue(theme[k])};`)

const generated = `/*
 * ⚠️ 이 파일은 생성물이다. 직접 고치지 않는다.
 *
 *   원본: src/design/tokens/{BlueLog,Light,Dark}.tokens.json  (디자인 담당 Figma 내보내기)
 *   생성: npm run build:tokens   (scripts/build-tokens.mjs)
 *
 * 값을 바꾸려면 JSON을 고치고 위 명령을 다시 돌린다. CI가
 * \`git diff --exit-code\`로 동기화를 검사하므로, 생성을 잊으면 빌드가 실패한다.
 *
 * ── 테마 규칙 (3-상태) ────────────────────────────────────────────────────
 * 뷰어의 테마 상태는 셋이다.
 *
 *   1. 명시적 선택 → <html data-theme="light|dark">
 *   2. 시스템 설정(기본) → 속성 없음. prefers-color-scheme만으로 갈린다
 *
 * 그래서 색은 세 곳에 정의한다.
 *
 *   :root                                          → 라이트 팔레트 (기본값)
 *   @media (prefers-color-scheme: dark)            → 다크. 단 [data-theme="light"]는 제외
 *     :root:not([data-theme='light'])                 (명시적 라이트 선택이 OS 다크를 이긴다)
 *   :root[data-theme='dark']                       → 명시적 다크 선택이 OS 라이트를 이긴다
 *
 * **색을 미디어 쿼리나 [data-theme] 블록 안에서만 정의하면 안 된다** — 속성이 없는
 * 기본 상태에서 그 색이 적용되지 않아 한쪽 테마의 글자가 다른 테마의 바탕 위에 얹힌다.
 */

:root {
${block(primitiveLines)}

  /* ── 색 · 라이트 (기본값) ──────────────────────────────────── */
${block(colorLines(light))}
}

/*
 * 시스템이 다크이고 사용자가 라이트를 명시하지 않은 경우.
 * 색 토큰만 다시 정의한다 — 치수·타이포는 테마와 무관하다.
 */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
${block(colorLines(dark), '    ')}
  }
}

/* 사용자가 다크를 명시한 경우 — OS가 라이트여도 이긴다. */
:root[data-theme='dark'] {
${block(colorLines(dark), '  ')}
}
`

writeFileSync(OUTPUT, generated, 'utf8')

const colorCount = Object.keys(light).length
console.log(
  `tokens.css 생성 완료 — 치수 ${primitiveLines.filter((l) => l.startsWith('--')).length}개 · 색 ${colorCount}개 × 2테마`,
)
