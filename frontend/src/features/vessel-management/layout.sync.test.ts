/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 선박 목록의 넘침은 **카드 안에서** 받는다 (#1788 · `#1689`와 같은 처리).
 *
 * ## 무엇이 문제였나
 *
 * 목록이 `890px`(열 최소폭 합 `806` + 거터 `7 × 12 = 84`) 밑으로 줄지 않는데 그 넘침을
 * 받아 주는 자리가 없었다. 그래서 넘침이 `vessel-management` → `app-shell__content`까지
 * 그대로 전해져 **1100 · 720에서 페이지가 통째로 가로로 밀렸다** — 실측 문서 폭 `1,195px`.
 *
 * 표 하나가 잘리는 것과 다르다. **사이드바와 페이지 제목까지 함께 빠져나가** 되돌아올
 * 기준점이 사라지고, `#1783`이 카드 밖에 둔 검색·선종 줄도 같이 밀려 **조건을 지우려고
 * 왼쪽으로 되밀어야** 했다.
 *
 * ## 왜 검사로 두나
 *
 * 화면이 깨지지 않는다 — 가로로 밀 수 있으니 값은 다 보인다. 좁은 창에서만, 그것도
 * 「좀 불편하다」로만 드러난다. `#1689`가 같은 계열의 결함을 고치며 남긴 두 줄을 여기서
 * 지킨다: **실측값으로 최소 폭을 둔다 · 좁으면 가로로 스크롤하고 열을 접어 숨기지 않는다.**
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))
const CSS = readFileSync(join(HERE, 'VesselManagement.css'), 'utf-8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

/** `#1788` 실측 — 1440 · 라이트 · 시연 데이터에서 칸을 좁혀 잰 행의 `scrollWidth`. */
const MEASURED_MIN = 890

describe('선박 목록의 넘침은 카드 안에서 받는다 (#1788)', () => {
  it('목록을 감싼 자리가 가로로 스크롤한다 — 페이지가 밀리지 않는다', () => {
    expect(/\.vm__list-wrap\s*\{[^}]*overflow-x:\s*auto/.test(CSS)).toBe(true)
  })

  it('최소 폭을 실측값(890) 아래로 되돌리지 않는다', () => {
    const match = /\.vm__list\s*\{[^}]*min-inline-size:\s*([0-9]+)px/.exec(CSS)
    expect(match, 'VesselManagement.css에서 목록 최소 폭을 찾지 못했다').not.toBeNull()
    expect(Number(match![1])).toBeGreaterThanOrEqual(MEASURED_MIN)
  })

  it('열 최소폭 합이 그 실측값과 맞는다 — 열을 늘리면 최소 폭도 함께 올린다', () => {
    const cols = /--vm-cols:([^;]+);/.exec(CSS)
    expect(cols, '열 정의(`--vm-cols`)를 찾지 못했다').not.toBeNull()
    /*
     * `32px` · `minmax(170px, …)` 양쪽에서 **첫 px 값**을 모은다 — 그것이 그 열이
     * 줄어들 수 있는 하한이다.
     */
    const mins = [...cols![1].matchAll(/(?:minmax\(\s*)?(\d+)px/g)].map((m) => Number(m[1]))
    expect(mins).toHaveLength(8)
    const gap = 12
    expect(mins.reduce((a, b) => a + b, 0) + (mins.length - 1) * gap).toBe(MEASURED_MIN)
  })

  /*
   * 래퍼만으로는 모자랐다 — 실측에서 720의 문서 폭이 `927px`로 남아 있었고, 범인은
   * 각 칸의 **보이지 않는** `sr-only` 라벨이었다. `position: absolute`인데 위치를 잡아
   * 주는 조상이 없어 컨테이닝 블록이 문서 전체가 되고, 그래서 래퍼의 `overflow`가
   * 자르지 못했다. **가로 스크롤의 정체가 보이지 않는 요소**라 눈으로는 찾을 수 없다.
   */
  it('행이 `sr-only`의 컨테이닝 블록이다 — 안 그러면 래퍼가 자르지 못한다', () => {
    expect(/\.vm__head,\s*\n\.vm__row\s*\{[^}]*position:\s*relative/.test(CSS)).toBe(true)
  })

  it('좁다고 열을 접어 숨기지 않는다 (#1689)', () => {
    // 열을 없애는 미디어 규칙이 생기면 좁은 폭에서만 다른 화면이 된다.
    expect(CSS).not.toMatch(/@media[^{]*\{[^}]*\.vm__(head|row)\s*\{[^}]*display:\s*none/)
  })
})
