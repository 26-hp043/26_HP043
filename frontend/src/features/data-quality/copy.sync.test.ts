/**
 * 데이터 점검 심각도 이름이 **정본과 같은가** (`#1604`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 정본 동기화 검사)
 *
 * ## 무엇이 어긋나 있었나
 *
 * `#1532`(결정 `D-29`)가 심각도 이름을 「실적 미입력」 → **「실적 확정 전」**으로 바꾸고
 * `DESIGN_SYSTEM §2.3.1` 🔒에 반영했는데(`#1606`), 화면 문구는 옛 이름 그대로였다.
 *
 * 그래서 **같은 항차를 두 이름으로 불렀다** — 대시보드 카드는 「실적 확정 전 항차」이고,
 * 거기서 「모두 보기」로 들어간 데이터 점검은 「실적 미입력」이었다.
 *
 * ## 왜 정본을 읽어 대조하는가
 *
 * 화면에 문자열을 적어 두는 검사는 **같이 낡는다** — 정본이 다시 바뀌면 검사도 함께
 * 고쳐야 하고, 고치지 않으면 옛 이름을 지키는 검사가 된다(`#1780`에서 실제로 그랬다).
 * `DESIGN_SYSTEM §2.3.1` 표에서 이름을 읽어 대조한다.
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { SEVERITY_TITLE } from './copy'

const spec = readFileSync(join(__dirname, '../../../../DESIGN_SYSTEM.md'), 'utf-8')

/** `§2.3.1` 심각도 표의 첫 칸(이름)들. */
function severityNames(): string[] {
  const start = spec.indexOf('### 2.3.1')
  expect(start, '§2.3.1을 찾지 못했다').toBeGreaterThan(-1)
  const section = spec.slice(start, spec.indexOf('\n### ', start + 10))
  return [...section.matchAll(/^\|\s*([^|]+?)\s*\|/gm)]
    .map((match) => match[1].trim())
    .filter((name) => name !== '' && !/^-+$/.test(name) && name !== '심각도' && name !== '이름')
}

describe('심각도 이름이 정본과 같다 (#1604)', () => {
  it('§2.3.1 표를 읽을 수 있다', () => {
    expect(severityNames().length).toBeGreaterThan(3)
  })

  it('화면이 쓰는 이름이 모두 정본 표에 있다', () => {
    // 옛 이름(「실적 미입력」)이 남아 있으면 여기서 걸린다 — 표에 없는 이름이기 때문이다.
    const names = severityNames()
    for (const title of Object.values(SEVERITY_TITLE)) {
      expect(names, `정본 §2.3.1에 없는 이름: ${title}`).toContain(title)
    }
  })

  it('「실적 확정 전」을 쓴다 — 대시보드 카드와 같은 이름이다', () => {
    /*
     * 이 한 줄만 이름을 직접 적는다. 위 검사는 「표에 있는가」만 보므로, 표에 옛 이름이
     * 남아 있으면 통과해 버린다 — 이 결함의 본체(두 화면이 다른 이름)를 못 잡는다.
     */
    expect(Object.values(SEVERITY_TITLE)).toContain('실적 확정 전')
    expect(Object.values(SEVERITY_TITLE)).not.toContain('실적 미입력')
  })
})
