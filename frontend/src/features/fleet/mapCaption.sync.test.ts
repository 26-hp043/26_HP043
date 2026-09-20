/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 지도(`FleetMap`) ↔ 개략도(`PositionChart`) **캡션 드리프트 가드** (`#1421`).
 *
 * ## 무엇이 문제였나
 *
 * `DESIGN_SYSTEM §9.5` 🔒는 「**개략도도 같은 문장을 쓴다** — 자산 유무로 두 그림이
 * 갈리는데 읽는 법이 다르면 사용자는 다른 그림으로 읽는다」로 닫혀 있다. 그런데
 * 지도 캡션은 「테두리가 굵은 **표**」로 적고 있었다 — 개략도는 「배」다. **같은
 * 표식을 두 화면이 다른 이름으로 부르고 있었고**, 자산 유무로 그림이 갈리는 자리라
 * 한 사용자는 둘 중 하나만 본다. 눈으로 대조할 기회조차 없다.
 *
 * ## 왜 화면 테스트가 못 잡았나
 *
 * 두 캡션은 각자의 파일에 문자열로 박혀 있다. 한쪽만 고치는 편집은 **양쪽 테스트를
 * 모두 통과**한다 — 어느 테스트도 다른 파일을 보지 않기 때문이다.
 *
 * ## 여기서 보는 것
 *
 * 굵은 테두리를 설명하는 **절이 두 파일에서 한 글자까지 같다.** 문구 자체는
 * 바꿔도 된다(`AGENTS §4.6` 표시 문구) — **둘이 함께** 바뀌어야 할 뿐이다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))

/**
 * 소스에서 캡션 평문을 뽑는다.
 *
 * 주석을 **먼저** 걷어낸다 — 두 파일 모두 본문보다 주석에서 「테두리」를 훨씬 자주
 * 말하므로, 주석을 남기면 엉뚱한 줄을 캡션으로 집는다. JSX 표기(`<b>`·`{' '}`·
 * 조건식)도 사람이 읽는 글자가 아니므로 함께 지운다.
 */
function plainText(file: string): string {
  return readFileSync(join(HERE, file), 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, ' ')
    .replace(/\{[^{}]*\}/g, ' ')
    // 태그는 **빈 문자열**로 지운다 — 공백으로 바꾸면 `<b>…</b>는`이 「… 는」이 된다.
    .replace(/<[^>]*>/g, '')
    .replace(/\s+/g, ' ')
}

/** 「테두리」로 시작해 문장이 끝날 때까지 — 두 파일이 공유하는 절이다. */
function borderClause(file: string): string[] {
  return plainText(file).match(/테두리[^.]*\./g) ?? []
}

describe('지도와 개략도가 굵은 테두리를 같은 말로 설명한다 (DESIGN_SYSTEM §9.5 🔒)', () => {
  it('두 파일 모두 굵은 테두리를 설명하는 절을 하나씩 가진다', () => {
    // 추출 자체가 깨지면 아래 대조가 무의미해진다 — `daysReason.sync.test.ts`와 같은 이유다.
    expect(borderClause('FleetMap.tsx')).toHaveLength(1)
    expect(borderClause('PositionChart.tsx')).toHaveLength(1)
  })

  it('그 절이 한 글자까지 같다 — 한쪽만 고치면 여기서 걸린다', () => {
    const [map] = borderClause('FleetMap.tsx')
    const [chart] = borderClause('PositionChart.tsx')
    expect(
      map,
      '두 캡션이 갈렸다. 문구를 바꿀 때는 FleetMap.tsx와 PositionChart.tsx를 함께 고칠 것',
    ).toBe(chart)
  })
})
