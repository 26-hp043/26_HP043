/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 카드·입력 규격 가드 — `DESIGN_SYSTEM §5` · `§8`.
 *
 * ## 왜 필요한가
 *
 * `§5`의 한 줄이 스무 개 파일에 **손으로 복사돼** 있다.
 *
 * > **카드/패널**: surface · border · radius 12 · 그림자 Lv1 · 패딩 16–20
 *
 * 복사본은 갈라진다. 실제로 갈라진 방향이 한쪽으로 몰려 있었다 — **정상 결과
 * 패널에는 그림자가 있고, 빈 상태·로딩·에러 패널에는 없었다.** 그 화면을 만들 때는
 * 정상 상태만 보고 있었기 때문이다.
 *
 * 결과는 「상태가 바뀌면 칸이 납작해진다」였고, 이건 **화면을 그 상태로 만들어
 * 봐야만** 눈에 띈다. 시연 중에 처음 보게 되는 종류의 결함이다.
 *
 * ## 무엇으로 판정하는가
 *
 * **`--radius-card`를 쓰면 카드다.** 이것이 이 파일의 유일한 판정 기준이다.
 *
 * 선택자 이름으로 판정하지 않는다 — `__panel`·`__card`·`__box`·이름 없는 것까지
 * 제각각이라 목록이 곧 낡는다. 반면 `radius-card`는 **「이건 카드다」라고 쓴 사람이
 * 직접 선언한 것**이라 이름 규칙보다 정확하다.
 *
 * 카드 안에 겹쳐 놓이는 항목(`.vessel`)은 `--radius-control`(8)을 쓰므로 대상이
 * 아니다. **의도한 제외다** — 카드 안의 카드에 그림자를 주면 층이 두 겹이 되고,
 * 그건 `§5`가 말하는 고도가 아니다.
 */

function collect(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules') continue
      out.push(...collect(full))
    } else if (entry.name.endsWith('.css')) {
      out.push(full)
    }
  }
  return out
}

const HERE = fileURLToPath(new URL('.', import.meta.url))
const files = collect(join(HERE, '..'))

interface Rule {
  file: string
  selector: string
  body: string
}

/** CSS 주석을 걷어낸다 — 규칙 검사가 설명 문장에 걸리지 않게 한다. */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '')
}

function rules(): Rule[] {
  const out: Rule[] = []
  for (const file of files) {
    const text = stripComments(readFileSync(file, 'utf-8'))
    for (const match of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      out.push({
        file: file.slice(HERE.length - 1),
        selector: match[1].trim().replace(/\s+/g, ' '),
        body: match[2],
      })
    }
  }
  return out
}

const ALL = rules()

/** 카드 면 — 생성 토큰과 호환 별칭 둘 다 쓰이고 있다. */
const CARD_SURFACE = /background[a-z-]*:\s*var\((--surface-card|--color-surface)\)/

describe('카드/패널 규격 — §5', () => {
  it('훑을 CSS 파일을 실제로 찾았다', () => {
    expect(files.length).toBeGreaterThanOrEqual(15)
  })

  it('카드 규격을 실제로 쓰는 규칙이 있다 — 가드가 헛돌지 않는다', () => {
    const cards = ALL.filter(
      (r) => CARD_SURFACE.test(r.body) && /border-radius:\s*var\(--radius-card\)/.test(r.body),
    )
    expect(cards.length).toBeGreaterThanOrEqual(10)
  })

  /*
   * 실패 메시지가 **고칠 방법을 함께 낸다.** 규격을 외우고 있어야 고칠 수 있는
   * 가드는 다음 사람에게 두 번 일을 시킨다.
   */
  it('카드 면 + radius-card면 그림자 Lv1이 있다', () => {
    const missing = ALL.filter(
      (r) =>
        CARD_SURFACE.test(r.body) &&
        /border-radius:\s*var\(--radius-card\)/.test(r.body) &&
        !/box-shadow/.test(r.body),
    ).map((r) => `${r.file}  ${r.selector}`)

    expect(
      missing,
      `§5는 「카드/패널: surface · border · radius 12 · 그림자 Lv1」입니다.\n` +
        `아래 규칙에 \`box-shadow: var(--shadow-lv1);\`을 더하십시오.\n` +
        `카드가 아니라 카드 안에 겹쳐 놓이는 항목이라면 \`--radius-control\`을 쓰십시오.\n\n` +
        missing.join('\n'),
    ).toEqual([])
  })
})

describe('입력·셀렉트 규격 — §8', () => {
  /**
   * `§8`: 「**입력·셀렉트**: surface-2 배경 · border · radius 8 · 라벨 상단 · 포커스 링」
   *
   * 입력칸이 카드와 **같은 흰색**이면 카드 위에서 테두리 하나로만 갈린다. 어디를
   * 채워야 하는지가 테두리 1px에 걸리고, 배경이 쿨톤으로 바뀌면서 그 1px이 더 얕아졌다.
   *
   * 실제로 두 갈래로 갈려 있었다 — 연간 등급·항로 비교·선박 관리는 `surface-2`,
   * 설정·보고서·선박 상세·항차는 카드 흰색. **같은 제품에서 입력칸이 화면마다
   * 다르게 생긴 상태**였다.
   */
  it('입력·셀렉트에 카드 면을 쓰지 않는다', () => {
    const offenders = ALL.filter(
      (r) => /\b(input|select|textarea)\b/.test(r.selector) && CARD_SURFACE.test(r.body),
    ).map((r) => `${r.file}  ${r.selector}`)

    expect(
      offenders,
      `§8은 입력·셀렉트에 **surface-2** 배경을 씁니다.\n` +
        `\`var(--surface-inset)\`(또는 별칭 \`var(--color-surface-2)\`)로 바꾸십시오.\n\n` +
        offenders.join('\n'),
    ).toEqual([])
  })
})
