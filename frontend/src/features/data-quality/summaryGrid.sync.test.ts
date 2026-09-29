/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { dirOf } from '../../test/srcPaths'
import { SEVERITY_TITLE } from './copy'

/**
 * **칸 수가 고정이면 열 수도 그 약수여야 한다** (`#2050`).
 *
 * ## 무엇이 어긋나 있었나
 *
 * 요약 띠는 칸이 **여섯**으로 고정이다 — 심각도 다섯(`SEVERITY_TITLE`)과 완결성 하나.
 * 그런데 열 수는 `repeat(auto-fit, …)`가 **폭에 따라** 정했다. `auto-fit`은 들어가는
 * 만큼 채우고 남는 칸을 늘리므로, 여섯이 한 줄에 안 들어가면 다섯을 놓고 나머지
 * 하나가 **한 줄을 혼자 다 쓴다.** 6의 약수가 아닌 열 수에서는 반드시 깨진다.
 *
 * 실측에서 1440 창의 실제 자리(약 1049)가 `5 + 1`이었고, 더 좁히면 `4 + 2`였다.
 *
 * ## 이 검사가 보는 것
 *
 * 화면을 재지 않는다 — jsdom은 배치를 하지 않고, 격자 계산은 브라우저의 일이다.
 * 대신 **산술**을 본다: 선언한 열 수가 칸 수의 약수인가. 그것만 지키면 마지막 줄이
 * 늘 꽉 찬다.
 *
 * 그래서 이 검사는 **칸이 늘거나 줄 때도** 붉어진다 — 일곱 번째 칸이 생기면 6의
 * 약수로 적어 둔 열 수가 전부 7의 약수가 아니게 되기 때문이다. 고쳐야 할 것이
 * 열 수라는 사실이 그때 드러난다.
 */
const HERE = dirOf(import.meta.url)

/** 완결성 칸 하나 — 심각도가 아니라 화면이 직접 그린다. */
const COMPLETENESS_TILES = 1

function css(): string {
  return readFileSync(join(HERE, 'DataQuality.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
}

/** `.dq__tiles`에 걸린 모든 `repeat(N, …)`의 N. */
function declaredColumns(): number[] {
  const out: number[] = []
  for (const rule of css().matchAll(/\.dq__tiles\s*\{([^}]*)\}/g)) {
    const repeat = /grid-template-columns:\s*repeat\(\s*([^,\s]+)/.exec(rule[1])
    if (repeat === null) continue
    out.push(Number(repeat[1]))
  }
  return out
}

describe('데이터 점검 요약 띠의 마지막 줄이 늘 꽉 찬다 (#2050)', () => {
  const tiles = Object.keys(SEVERITY_TITLE).length + COMPLETENESS_TILES

  it('칸은 여섯이다 — 심각도 다섯 + 완결성', () => {
    // 이 수가 바뀌면 아래 열 수도 함께 가야 한다. 그 사실을 여기서 못 박는다.
    expect(tiles).toBe(6)
  })

  it('화면이 그리는 칸 수가 그 여섯과 같다', () => {
    const view = readFileSync(join(HERE, 'DataQuality.tsx'), 'utf8')
    const listed = /\((\[[^\]]*\] as const)\)\.map/.exec(view)
    expect(listed, '요약 띠가 심각도 배열을 map 하지 않습니다').not.toBeNull()
    const severities = (listed![1].match(/'[A-Z_]+'/g) ?? []).length
    expect(severities + COMPLETENESS_TILES).toBe(tiles)
  })

  it('선언한 열 수가 전부 칸 수의 약수다', () => {
    const columns = declaredColumns()
    expect(columns.length, '`.dq__tiles`에 `repeat(N, …)` 선언이 없습니다').toBeGreaterThan(0)
    expect(columns.filter((n) => !Number.isInteger(n) || tiles % n !== 0)).toEqual([])
  })

  it('⚠️ `auto-fit`을 쓰지 않는다 — 열 수를 폭이 정하면 약수를 보장할 수 없다', () => {
    /*
     * `auto-fit`·`auto-fill`은 **몇 열이 될지 CSS가 말하지 않는다.** 위 약수 검사가
     * 볼 수 있는 것이 사라지므로, 값이 아니라 **수단**을 막는다.
     */
    expect(css()).not.toMatch(/\.dq__tiles\s*\{[^}]*auto-(fit|fill)/)
  })

  it('자리 폭을 기준으로 잰다 — 창 폭이 아니라', () => {
    /*
     * 띠가 놓이는 폭은 사이드바와 여백을 뺀 값이라 창 폭과 다르다(1440 창에서 약
     * 1049). 창을 기준으로 전환점을 적으면 셸이 바뀔 때 어긋난다.
     */
    expect(css()).toMatch(/\.dq\s*\{[^}]*container-type:\s*inline-size/)
    expect(css()).toMatch(/@container\s*\(min-width:/)
  })
})
