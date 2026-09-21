/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { TARGET_DEFAULT } from './annualRules'

/**
 * 목표 등급 기본값 드리프트 가드 (`#1453`).
 *
 * ## 무엇이 문제였나
 *
 * 같은 값이 **세 곳**에 따로 적혀 있었다 — `PRD §12.2` 입력 표(C) · 같은 절의 요청
 * 예시(B) · 화면 초깃값(B). 화면이 예시를 따르면서 정본 표와 갈렸고, 어느 쪽도 다른
 * 쪽을 보지 않아 아무것도 실패하지 않았다.
 *
 * 대부분의 사용자는 첫 값을 바꾸지 않고 실행하므로, 기본값이 틀리면 「B 이상 받을 확률」이
 * **사용자가 고른 적 없는 목표**로 나온다 — 화면에 틀린 값이 보이지 않는 채로 결과가 바뀐다.
 *
 * ## 여기서 보는 것
 *
 * 표의 기본값을 소유절로 두고, 예시와 화면이 그것과 같은지 본다.
 * `daysReason.sync.test.ts`가 `API_SPEC` 표를 읽는 것과 같은 방식이다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const PRD = readFileSync(join(HERE, '..', '..', '..', '..', 'PRD.md'), 'utf-8')

/** `PRD §12.2` 입력 표의 `target_rating` 행에서 기본값 열(네 번째)을 읽는다. */
function tableDefault(): string | null {
  const row = PRD.split('\n').find((line) => /^\|\s*`target_rating`\s*\|\s*Y\s*\|/.test(line))
  if (!row) return null
  return row.split('|').map((cell) => cell.trim())[4] ?? null
}

/** 같은 절의 요청 예시 JSON에 적힌 값. */
function exampleValue(): string | null {
  return /"target_rating":\s*"([A-E])"/.exec(PRD)?.[1] ?? null
}

describe('연간 등급 목표 기본값이 세 곳에서 같다 (#1453)', () => {
  it('파싱 자체가 실패하지 않았다 — 헛돌면 아래가 전부 무의미해진다', () => {
    expect(tableDefault()).toMatch(/^[A-E]$/)
    expect(exampleValue()).toMatch(/^[A-E]$/)
  })

  it('화면 초깃값이 PRD 입력 표와 같다', () => {
    expect(TARGET_DEFAULT).toBe(tableDefault())
  })

  it('PRD 요청 예시가 같은 문서의 입력 표와 같다 — 종전에는 예시만 B였다', () => {
    expect(exampleValue()).toBe(tableDefault())
  })
})
