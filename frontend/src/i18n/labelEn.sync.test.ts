/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 영문 보조 라벨이 게이트 없이 다시 붙는 것을 막는다 (`#1426`).
 *
 * ## 왜 화면 테스트만으로는 부족한가
 *
 * `#1426`이 걷은 것은 **13곳**이다. 다음에 누가 한 곳을 되돌리거나 새 화면에 같은
 * 표기를 더해도, 그 화면의 테스트만 통과하면 아무것도 걸리지 않는다 — 다른 화면의
 * 검사는 그 파일을 보지 않기 때문이다. 화면이 늘수록 다시 벌어지는 유형이고,
 * `§3` 🔒이 「영문 **약어** 병기」로 닫아 둔 자리라 벌어지면 정본 위반이다.
 *
 * ## 여기서 보는 것
 *
 * 영문 보조 라벨의 클래스(`…title-en` · `…label-en`)를 쓰는 파일은 **전부**
 * `useShowsLabelEn` 게이트를 함께 써야 한다. 게이트 없이 그리면 한국어 모드에서도
 * 나온다.
 *
 * **예외를 목록으로 두지 않는다.** 목록이 생기는 순간 「예외에 넣으면 된다」가 되고,
 * 그것이 `#748`이 밟은 길이다. 화면 이름처럼 게이트가 필요 없는 자리는 **클래스를
 * 아예 쓰지 않는 쪽**으로 고쳤으므로 이 규칙에 걸리지 않는다.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url))

/** 영문 보조 라벨 클래스를 `className`에 쓰는 자리. */
const LABEL_EN_CLASS = /className="[^"]*(?:title|label)-en[^"]*"/

function tsxFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) tsxFiles(full, out)
    else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) out.push(full)
  }
  return out
}

function offenders(): string[] {
  const found: string[] = []
  for (const file of tsxFiles(SRC)) {
    const body = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, ' ')
    if (!LABEL_EN_CLASS.test(body)) continue
    if (!body.includes('useShowsLabelEn')) found.push(file.slice(SRC.length))
  }
  return found
}

function users(): string[] {
  return tsxFiles(SRC)
    .filter((file) => LABEL_EN_CLASS.test(readFileSync(file, 'utf-8')))
    .map((file) => file.slice(SRC.length))
}

describe('영문 보조 라벨은 게이트 뒤에 있다 (#1426 · DESIGN_SYSTEM §3 🔒)', () => {
  it('보는 자리가 실제로 있다 — 정규식이 헛돌면 아래가 공집합 통과가 된다', () => {
    expect(users().length).toBeGreaterThan(3)
  })

  it('영문 보조 라벨을 그리는 파일은 전부 useShowsLabelEn을 쓴다', () => {
    expect(
      offenders(),
      '한국어 모드에서도 영문이 나온다 — useShowsLabelEn으로 감쌀 것',
    ).toEqual([])
  })
})
