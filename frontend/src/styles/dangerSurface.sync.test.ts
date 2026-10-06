import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 위험색을 **면**으로 쓰지 않는다 — `DESIGN_SYSTEM §2.3` 〔확정 2026-09-22 · `#1690`〕.
 *
 * > 카드 테두리 · 조치 필요 행 · 요약 칸의 **면은 중립**으로 두고, 위험색은
 * > **아이콘과 문구에만** 쓴다
 *
 * ## 왜 한 곳에서 전 화면을 보는가
 *
 * `#1979`에서 규제 기준값의 「기준값 바꾸기」 버튼이 `--color-danger-text`를 **배경**으로
 * 칠하고 있었다. 같은 성격의 자리(탈퇴하기 · 연료 행 삭제 · 숫자 위험 표기)는 전부
 * 테두리 + 글자색인데 **이 버튼만** 달랐고, 화면별 테스트는 자기 화면만 보므로 그
 * 갈라짐을 아무도 잡지 못했다.
 *
 * 더 나쁜 것은 **제가 `#1542` 검토에서 「색은 집 규칙과 맞다」고 적었다**는 점이다 —
 * 사람이 읽어도 놓치는 자리라 계산으로 건다.
 *
 * ## 무엇을 거는가
 *
 * 위험색 토큰을 **그대로** 면에 까는 것만 막는다. `color-mix(… 8%, surface)`처럼
 * **옅게 섞은** 배경은 통과한다 — 그것은 이미 중립에 가까운 면이고, `--*-soft` 계열이
 * 하는 일과 같다(종전 `FleetDashboard.css`의 배너가 그 자리였다 — `#2206`에서 배너도 면을
 * 걷고 왼쪽 띠로 바꿨다). 「면은 중립」이 금지하는 것은
 * **위험색 자체를 면으로 쓰는 것**이다.
 */
const CSS_ROOT = join(import.meta.dirname, '..')

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return cssFiles(path)
    return path.endsWith('.css') ? [path] : []
  })
}

/** `background: var(--color-danger…)` — 함수로 감싸지 않고 토큰을 그대로 깐 것. */
const SOLID_DANGER_SURFACE =
  /background(?:-color)?:\s*var\(--(?:color-danger|semantic-danger)[a-z-]*\)/g

describe('위험색은 면이 아니라 테두리·글자로 (§2.3 · #1979)', () => {
  it('어느 화면도 위험색 토큰을 그대로 배경으로 깔지 않는다', () => {
    const offenders: string[] = []
    for (const file of cssFiles(CSS_ROOT)) {
      const source = readFileSync(file, 'utf8')
      for (const hit of source.matchAll(SOLID_DANGER_SURFACE)) {
        offenders.push(`${file.slice(CSS_ROOT.length + 1)} — ${hit[0]}`)
      }
    }
    expect(
      offenders,
      '§2.3 「면은 중립으로 두고 위험색은 아이콘과 문구에만」\n  ' + offenders.join('\n  '),
    ).toEqual([])
  })

  /*
   * 규칙이 **무언가를 보고 있는지** 확인한다. 정규식이 조용히 아무것도 안 잡게 되면
   * 위 검사는 영원히 초록이다 — `#1770`이 「문구가 있는가」만 보다 겪은 일과 같다.
   */
  it('그 검사가 실제로 잡는다 — 되돌린 선언을 넣어 보면', () => {
    const reverted = '.x { background: var(--color-danger-text); }'
    expect([...reverted.matchAll(SOLID_DANGER_SURFACE)]).toHaveLength(1)

    // 옅게 섞은 면은 통과한다 — 그것은 중립에 가까운 배경이다
    const tint = '.y { background: color-mix(in srgb, var(--color-danger) 8%, var(--color-surface)); }'
    expect([...tint.matchAll(SOLID_DANGER_SURFACE)]).toHaveLength(0)
  })
})
