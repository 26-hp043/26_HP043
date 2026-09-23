/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { TOOL_LABELS, citeLabels } from './toolLabels'

/**
 * 도구 풀이집이 **서버가 실제로 가진 도구**를 다 덮는지 (#1818).
 *
 * 덮지 못하면 화면은 깨지지 않고 **근거 칩만 조용히 사라진다** — 새 도구가 답을 냈는데
 * 그 답만 근거가 없다. `shipTypes.sync.test.ts`가 `calc/capacity.py`를 대조하는 것과
 * 같은 자리다.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))
const CHAT_TOOLS = join(HERE, '..', '..', '..', '..', 'src', 'cii_platform', 'services', 'chat_tools.py')

function serverToolNames(): string[] {
  const source = readFileSync(CHAT_TOOLS, 'utf-8')
  const names = [...source.matchAll(/^TOOL_[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1])
  expect(names.length, 'chat_tools.py에서 TOOL_* 상수를 읽지 못했습니다').toBeGreaterThan(0)
  return names
}

describe('도구 풀이집이 서버와 맞는다 (#1818)', () => {
  it('서버의 도구가 모두 풀이집에 있다', () => {
    const missing = serverToolNames().filter((name) => !(name in TOOL_LABELS))
    expect(
      missing,
      `풀이집에 없는 도구가 있습니다: ${missing.join(', ')} — 그 답만 근거 칩이 비어 나갑니다.`,
    ).toEqual([])
  })

  it('풀이집에 서버에 없는 도구를 남겨 두지 않는다', () => {
    const server = new Set(serverToolNames())
    const stale = Object.keys(TOOL_LABELS).filter((name) => !server.has(name))
    expect(stale, `서버에서 사라진 도구입니다: ${stale.join(', ')}`).toEqual([])
  })

  it('풀이는 한국어이고 도구 이름을 그대로 쓰지 않는다', () => {
    for (const [name, label] of Object.entries(TOOL_LABELS)) {
      expect(label, `${name}의 풀이가 비어 있습니다`).toBeTruthy()
      expect(label).not.toContain('_')
      expect(/[가-힣]/.test(label), `${name}의 풀이에 한국어가 없습니다`).toBe(true)
    }
  })
})

describe('citeLabels', () => {
  it('없으면 빈 배열 — 빈 칩을 그리지 않는다', () => {
    expect(citeLabels(undefined)).toEqual([])
    expect(citeLabels([])).toEqual([])
  })

  it('같은 도구를 두 번 부르면 한 번만 적는다', () => {
    expect(citeLabels(['project_year_end', 'project_year_end'])).toEqual(['연말 예상 계산'])
  })

  it('모르는 이름은 날것으로 내보내지 않는다', () => {
    expect(citeLabels(['made_up_tool'])).toEqual([])
    expect(citeLabels(['made_up_tool', 'search_vessel'])).toEqual(['선박 찾기'])
  })
})
