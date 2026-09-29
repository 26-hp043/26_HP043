/**
 * 서버가 내는 사유 코드를 화면이 **전부 한국어로 옮기는가** (`#2019`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 정본 동기화 검사)
 *
 * ## 무엇이 비어 있었나
 *
 * `reasonText`는 모르는 코드를 **코드 그대로** 보인다. 빈칸으로 두면 문제가 없는 것처럼
 * 보이므로 그 폴백은 맞다(`copy.ts`). 그런데 폴백이 조용해서, 서버가 코드를 하나 늘리면
 * 화면에 영문 코드가 뜨는데 **아무 검사도 실패하지 않았다.**
 *
 * 옆의 `copy.sync.test.ts`는 「화면이 쓰는 심각도 이름이 정본에 있는가」를 본다. 이 파일은
 * 방향이 반대다 — **「정본에 있는 코드가 화면에 있는가」**. 새 코드를 잡는 것은 이쪽이다.
 *
 * ## 무엇과 대조하는가
 *
 * `API_SPEC §2.16` 심각도 표의 `codes` 열과 `cii_impact_reason` 행이다. 서버 쪽 한 자리
 * (`services/data_quality.py` `ISSUE_CODES`)가 그 표와 같은지는
 * `tests/test_data_quality_codes_sync.py`가 본다 — 두 검사가 사슬 전체를 덮는다.
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { IMPACT_REASON, reasonText } from './copy'

const spec = readFileSync(join(__dirname, '../../../../API_SPEC.md'), 'utf-8')

function section(): string {
  const start = spec.indexOf('### 2.16')
  expect(start, '§2.16을 찾지 못했다').toBeGreaterThan(-1)
  return spec.slice(start, spec.indexOf('\n### ', start + 10))
}

/** 칸 안의 코드 — `FUEL:<유종>`의 열린 값은 예시 유종(`HFO`)으로 채운다. */
function codesIn(cell: string): string[] {
  return [...cell.matchAll(/`([A-Z][A-Z0-9_]+(?::[A-Z0-9_]+)?)(:<[^>]+>)?`/g)].map((match) =>
    match[2] ? `${match[1]}:HFO` : match[1],
  )
}

/** 심각도 표의 `codes` 열 — 심각도마다. */
function issueCodes(): Map<string, string[]> {
  const text = section()
  const table = text.slice(text.indexOf('**`issues[].severity`**'))
  const rows = new Map<string, string[]>()
  for (const line of table.split('\n')) {
    const match = /^\|\s*`([A-Z_]+)`\s*\|[^|]*\|[^|]*\|([^|]*)\|\s*$/.exec(line)
    if (match) rows.set(match[1], codesIn(match[2]))
  }
  return rows
}

function impactReasons(): string[] {
  const row = section()
    .split('\n')
    .find((line) => line.startsWith('| `issues[].cii_impact_reason` |'))
  expect(row, '§2.16 cii_impact_reason 행을 찾지 못했다').toBeDefined()
  return codesIn(row!.split('|')[2])
}

describe('사유 코드가 모두 한국어로 옮겨진다 (#2019)', () => {
  it('§2.16 표를 읽을 수 있다', () => {
    // 파서가 표를 놓치면 아래 검사가 빈 목록으로 통과한다.
    const rows = issueCodes()
    expect([...rows.keys()].sort()).toEqual(
      ['ANOMALY', 'PUBLIC_RECORD', 'SUBSTITUTED', 'UNAVAILABLE', 'UNCONFIRMED'].sort(),
    )
    for (const codes of rows.values()) expect(codes.length).toBeGreaterThan(0)
    expect(impactReasons().length).toBeGreaterThan(0)
  })

  it('정본의 issues[].codes가 모두 문구로 옮겨진다', () => {
    for (const [severity, codes] of issueCodes()) {
      for (const code of codes) {
        const head = code.split(':')[0]
        // 모르는 코드는 원문(또는 `원문 (접미사)`)으로 나온다 — 앞머리가 그대로 남는다.
        expect(reasonText(code), `${severity} · ${code}가 코드 그대로 보인다`).not.toContain(head)
      }
    }
  })

  it('정본의 cii_impact_reason이 모두 문구로 옮겨진다', () => {
    for (const reason of impactReasons()) {
      expect(IMPACT_REASON[reason], `${reason}의 문구가 없다`).toBeDefined()
    }
  })
})
