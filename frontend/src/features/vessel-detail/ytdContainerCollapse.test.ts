/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * YTD 격자 컨테이너 쿼리 가드 (`#1352`).
 *
 * ## 무엇이 겹쳤는가
 *
 * 사이드바가 접히지 않는 좁은 화면(`DESIGN_SYSTEM §7.2` — 모바일 graceful degrade)에서는
 * 카드 폭이 `.ytd` 격자가 가정한 폭보다 훨씬 좁아진다. 종전에는 `@media (max-width: 1100px)`
 * 하나로 **뷰포트** 폭만 보고 2열로 접었는데, 사이드바 240px가 고정이라 뷰포트가
 * 좁아져도 카드 폭은 그에 비례해 줄지 않는다 — 400px 뷰포트에서 카드 실제 폭이
 * 100px 안팎까지 줄어, `minmax(0, 1fr)` 두 칸이 서로의 자리를 침범해 등급 배지가
 * 실적값 위에, 완료 항차 수가 기준값 위에 겹쳐 찍혔다(선박 상세·실시간 CII 둘 다).
 *
 * ## 왜 소스 검사인가
 *
 * `@container` 쿼리는 요소의 **실제 렌더 폭**을 재는데, `jsdom`(이 스위트의 렌더 환경)은
 * 레이아웃을 계산하지 않아 컨테이너 쿼리가 걸리는지 렌더 결과로는 확인할 수 없다.
 * `styles/cardSpec.test.ts`가 이미 쓰는 방식대로 CSS 소스 자체를 검사한다 — 컨테이너
 * 선언과 접는 규칙이 **둘 다** 있어야 실제로 걸린다.
 *
 * ## 이제 이 격자를 쓰는 화면은 하나다 (#1729)
 *
 * 선박 상세가 결론 띠(`DESIGN_SYSTEM §8.6`)로 바뀌며 YTD 카드를 더 쓰지 않는다. 규칙도
 * 남은 사용처인 실시간 CII로 옮겼다 — 검사도 그 파일 하나를 본다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REALTIME_CII_CSS = readFileSync(
  join(HERE, '../realtime-cii/RealtimeCiiView.css'),
  'utf-8',
)

function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** `@container (...) { ... }` 블록의 안쪽 본문만 뽑는다 — 중첩 중괄호를 직접 센다. */
function containerBlockBodies(text: string): string[] {
  const bodies: string[] = []
  const re = /@container[^{]*\{/g
  for (let match = re.exec(text); match !== null; match = re.exec(text)) {
    let depth = 1
    let i = re.lastIndex
    const start = i
    while (i < text.length && depth > 0) {
      if (text[i] === '{') depth++
      else if (text[i] === '}') depth--
      i++
    }
    bodies.push(text.slice(start, i - 1))
    re.lastIndex = i
  }
  return bodies
}

describe('YTD 격자 — 컨테이너 쿼리로 1열 접힘 (#1352)', () => {
  it('⚠️ 선박 상세에는 YTD 격자가 없다 — 결론 띠로 바뀌었다 (#1729)', () => {
    const body = stripComments(
      readFileSync(join(HERE, 'VesselDetail.css'), 'utf-8'),
    )
    expect(body).not.toMatch(/\.ytd\b/)
  })

  it('실시간 CII YTD 카드(.rt__ytd)가 컨테이너 쿼리 대상으로 선언돼 있다', () => {
    const body = stripComments(REALTIME_CII_CSS)
    expect(
      /\.rt__ytd\s*\{[^}]*container-type:\s*inline-size/.test(body),
      '.rt__ytd에 `container-type: inline-size`가 있어야 실시간 CII 카드도 같은 @container ' +
        '규칙의 적용을 받는다.',
    ).toBe(true)
  })

  it('카드 폭이 좁아지면 `.ytd`가 1열로 접힌다', () => {
    const body = stripComments(REALTIME_CII_CSS)
    const blocks = containerBlockBodies(body)
    const collapsesToOneColumn = blocks.some(
      (block) =>
        /\.ytd\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/.test(block) ||
        /\.ytd\s*\{[^}]*grid-template-columns:\s*1fr\s*;/.test(block),
    )

    expect(
      collapsesToOneColumn,
      '`@container` 블록 안에 `.ytd { grid-template-columns: minmax(0, 1fr) | 1fr; }`가 ' +
        '있어야 한다 — 2열 이상에서는 등급 배지·34px 수치·단위 딸린 값(예: `822.x t`)의 ' +
        '최소 폭이 카드 폭보다 넓어지는 지점에서 칸끼리 겹친다. 1열이면 다툴 옆 칸이 없다.',
    ).toBe(true)
  })

  it('값(`.ytd__figures dd`)이 좁은 칸 안에서 옆으로 흘러넘치지 않고 접힌다', () => {
    const body = stripComments(REALTIME_CII_CSS)
    const match = body.match(/\.ytd__figures dd\s*\{([^}]*)\}/)
    expect(match, '.ytd__figures dd 규칙을 찾지 못했다').not.toBeNull()
    expect(
      /overflow-wrap:\s*anywhere/.test(match![1]),
      '1열로 접혀도 극단적으로 좁은 카드에서는 34px 값 하나가 칸보다 넓을 수 있다. ' +
        '`overflow-wrap: anywhere`가 없으면 카드 밖으로 흘러넘쳐 옆 카드·사이드바 위에 ' +
        '겹쳐 보인다.',
    ).toBe(true)
  })
})
