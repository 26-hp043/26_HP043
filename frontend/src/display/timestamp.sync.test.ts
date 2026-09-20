/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 기준 시각을 화면이 직접 포맷하지 않는다 (#1420).
 *
 * ## 무엇이 문제였나
 *
 * `toLocaleString('ko-KR', { hour12: false })`을 화면이 각자 불렀다. 여섯 자리가 초까지
 * 찍고(「2026. 9. 20. 22시 37분 22초」) 대시보드 한 곳만 형식을 명시해 초를 껐다 —
 * **같은 성질의 값이 화면마다 달랐다.** 시간대도 브라우저를 따라 `§11`의 KST와 어긋났다.
 *
 * ## 소스를 읽는 이유
 *
 * 렌더 검사로는 「어느 화면이 직접 불렀나」를 볼 수 없다. 형식이 같아지는 순간 두 경로의
 * 결과가 같아져 동작이 구분되지 않기 때문이다 — `warningText.sync.test.ts`(#1292)가 사본을
 * 소스로 잡은 것과 같은 이유다.
 *
 * 숫자·용량 포맷은 대상이 아니다. 잡는 것은 **날짜·시각**을 만드는 호출뿐이다.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url))

/** 형식을 소유하는 파일. 여기서만 `toLocaleString`으로 날짜를 만든다. */
const OWNER = join(SRC, 'display', 'format.ts')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : []
  })
}

describe('날짜·시각 포맷은 display/format이 소유한다 (#1420)', () => {
  it('스캔 대상을 읽을 수 있다', () => {
    // 이 단언이 없으면 경로가 어긋난 순간부터 아래 검사가 **아무것도 보지 않는다.**
    expect(walk(SRC).length).toBeGreaterThan(100)
  })

  it('`new Date(...).toLocaleString`을 화면이 직접 부르지 않는다', () => {
    const offenders = walk(SRC)
      .filter((file) => file !== OWNER)
      .filter((file) => /new Date\([^)]*\)\s*\.toLocale(String|DateString|TimeString)/.test(readFileSync(file, 'utf-8')))
      .map((file) => file.slice(SRC.length))

    expect(
      offenders,
      `기준 시각은 formatTimestamp()를 쓴다: ${offenders.join(', ')}`,
    ).toEqual([])
  })
})
