import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { needsVesselNote, VESSEL_FREE_TOOLS } from './vesselNote'

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
})
