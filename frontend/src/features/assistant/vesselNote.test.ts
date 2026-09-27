import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { needsVesselNote, VESSEL_FREE_TOOLS, VESSEL_NOTE_STILL_APPLIES } from './vesselNote'

/**
 * 「선박을 먼저 골라 주세요」 안내를 언제 붙이는가 (#1535).
 *
 * 09-27 21:40 운영에서 선박 없이 규제값을 물었더니 `lookup_regulation`이 표를 읽어 제대로
 * 답했는데 말풍선이 그 안내로 시작했다. 안내는 **계산이 선박 때문에 못 돈 턴**에만 맞다.
 */
describe('needsVesselNote', () => {
  const base = { vesselResolved: false, discarded: false } as const

  it('선박 없이 도는 도구만으로 답했으면 붙이지 않는다', () => {
    expect(needsVesselNote({ ...base, toolCalls: ['lookup_regulation'] })).toBe(false)
    expect(needsVesselNote({ ...base, toolCalls: ['lookup_regulation', 'lookup_regulation'] })).toBe(false)
  })

  it('화면 결과 설명만으로 답했으면 붙이지 않는다 — 상단 선박 없이도 도는 도구다 (#1991)', () => {
    /*
     * 계산한 뒤 상단 셀렉트를 「선박 선택 안 함」으로 되돌리면 결과는 주소에 남고 상단
     * 선박만 없다. 서버는 그때 실행의 선박을 따지지 않고 저장된 결과를 읽어 **정상 답**을
     * 낸다 — 그 답에 「선박을 먼저 골라 주세요」가 붙으면 틀린 말이 된다.
     */
    expect(needsVesselNote({ ...base, toolCalls: ['explain_screen_result'] })).toBe(false)
    expect(needsVesselNote({ ...base, toolCalls: ['explain_screen_result', 'lookup_regulation'] })).toBe(false)
  })

  it('선박을 찾는 도구만 부른 턴에는 붙인다 — 아직 선박이 정해지지 않았다 (#1991)', () => {
    expect(needsVesselNote({ ...base, toolCalls: ['search_vessel'] })).toBe(true)
  })

  it('계산 도구가 끼어 있으면 붙인다 — 선박이 없어 그 도구는 못 돌았다', () => {
    expect(needsVesselNote({ ...base, toolCalls: ['lookup_regulation', 'calc_voyage_cii'] })).toBe(true)
    expect(needsVesselNote({ ...base, toolCalls: ['calc_voyage_cii'] })).toBe(true)
  })

  it('도구를 하나도 안 불렀으면 붙인다 — 종전 동작(#1243) 그대로', () => {
    expect(needsVesselNote({ ...base, toolCalls: [] })).toBe(true)
    expect(needsVesselNote({ ...base, toolCalls: undefined as unknown as readonly string[] })).toBe(true)
  })

  it('선박을 알거나 답을 버렸으면 붙이지 않는다', () => {
    expect(needsVesselNote({ vesselResolved: true, discarded: false, toolCalls: [] })).toBe(false)
    expect(needsVesselNote({ vesselResolved: undefined, discarded: false, toolCalls: [] })).toBe(false)
    expect(needsVesselNote({ vesselResolved: false, discarded: true, toolCalls: [] })).toBe(false)
  })
})

/**
 * 목록이 서버와 어긋나지 않는다 — 화면은 서버가 **선박 검사 앞에서** 부르는 도구만
 * 「선박 없이 돈다」고 믿어야 한다. 서버가 그 도구를 선박 검사 뒤로 옮기면 이 목록이
 * 거짓이 되는데, 화면은 깨지지 않아 조용히 틀린다.
 */
describe('VESSEL_FREE_TOOLS ↔ services/chat_tools.py', () => {
  const py = readFileSync(
    join(import.meta.dirname, '../../../../src/cii_platform/services/chat_tools.py'),
    'utf8',
  )
  const runTool = py.slice(py.indexOf('async def run_tool('))
  const vesselCheck = runTool.indexOf('if vessel_id is None:')

  it('목록의 도구는 run_tool에서 선박 검사보다 먼저 분기한다', () => {
    expect(vesselCheck, 'run_tool에 선박 검사가 있다').toBeGreaterThan(-1)
    for (const name of VESSEL_FREE_TOOLS) {
      const constant = py.match(new RegExp(`^(TOOL_[A-Z_]+) = "${name}"$`, 'm'))?.[1]
      expect(constant, `${name}의 상수가 있다`).toBeTruthy()
      const branch = runTool.indexOf(`if name == ${constant}:`)
      expect(branch, `${name} 분기가 있다`).toBeGreaterThan(-1)
      expect(branch, `${name} 분기가 선박 검사보다 앞이다`).toBeLessThan(vesselCheck)
    }
  })

  /*
   * ⚠️ **반대 방향도 본다** (`#1991`).
   *
   * 위 검사는 **목록 → 서버**(목록의 도구가 선박 검사 앞인가)만 본다. 그래서 서버가 선박
   * 검사 앞에 도구를 하나 더 두고 화면 목록에 넣지 않아도 **조용히 통과**했다 —
   * `explain_screen_result`가 실제로 그 상태였다.
   *
   * 빠진 것이 실수인지 판단인지 가리려면 **명시적 제외 목록**이 있어야 한다. 둘 중 어느
   * 목록에도 없으면 실패하므로, 새 도구를 선박 검사 앞에 두는 사람은 「선박 없이 도는가」를
   * 정하지 않고는 지나갈 수 없다.
   */
  it('선박 검사 앞에서 분기하는 도구는 모두 두 목록 중 하나에 있다 (#1991)', () => {
    const before = runTool.slice(0, vesselCheck)
    const branched = [...before.matchAll(/if name == (TOOL_[A-Z_]+):/g)].map((match) => match[1])
    expect(branched.length, '선박 검사 앞 분기를 찾았다').toBeGreaterThan(1)

    for (const constant of branched) {
      const name = py.match(new RegExp(`^${constant} = "([a-z_]+)"$`, 'm'))?.[1]
      expect(name, `${constant}의 값을 찾았다`).toBeTruthy()
      expect(
        VESSEL_FREE_TOOLS.has(name as string) || VESSEL_NOTE_STILL_APPLIES.has(name as string),
        `${name}이(가) 선박 검사 앞에서 도는데 두 목록 어디에도 없다 — ` +
          '선박 없이 낸 답에 안내를 붙일지 정하고 목록에 적는다 (#1991)',
      ).toBe(true)
    }
  })

  it('두 목록이 겹치지 않는다 — 같은 도구가 양쪽에 있으면 판단이 둘이다', () => {
    for (const name of VESSEL_FREE_TOOLS) expect(VESSEL_NOTE_STILL_APPLIES.has(name)).toBe(false)
  })
})
