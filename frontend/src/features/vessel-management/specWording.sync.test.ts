import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { dirOf } from '../../test/srcPaths'
import { SORT_LABEL, specGapFilterNotice } from './listRules'
import { activeFilters } from './queryRules'
import { unavailableText } from '../fleet/fleetRules'

/**
 * **화면 어휘와 서버 어휘가 같은 말을 쓰지 않는다** (`#2037`).
 *
 * ## 무엇이 갈려 있었나
 *
 * 이 화면의 칩 · 필터 · 정렬은 **용량 · 기준속도 · 기준 일일 연료소모량** 셋 중
 * 하나라도 비면 걸린다(`hasSpecGap`). 서버의 `MISSING_SPEC`은 **선종 · DWT · GT**를
 * 본다. 겹치는 것은 **용량 하나**뿐이다 — CII는 `M / (W · Dt)`라 기준속도·일일 연료는
 * 등급 계산에 들어가지 않는다.
 *
 * 그런데 둘 다 「제원」이라는 낱말을 썼다. `#2018`이 등급 칸을 넣으면 한 화면에
 * 「제원 미비」(칩)와 「제원 미입력」(등급 칸)이 **함께 뜨고**, 사용자는 **기준속도만
 * 빈 배가 칩에 걸리면서 등급은 멀쩡한** 상태를 설명할 길이 없다.
 *
 * `listRules.ts`가 이 실패를 이미 경고하고 있었다 — *「둘이 갈리면 … **같은 화면의 두
 * 컨트롤이 같은 말을 다르게 세는 셈이다**」*. `#1424`는 화면 **안**의 두 컨트롤을
 * 맞추며 그것을 적었고, `#2037`은 같은 일이 **화면과 서버 사이**에서 일어난 것이다.
 *
 * ## 이 검사가 보는 것
 *
 * **낱말이 겹치지 않는지**를 본다. 값을 비교하는 것이 아니라 *두 어휘가 서로를
 * 침범하지 않는지*를 보므로, 어느 한쪽 문구를 고쳐도 살아 있다.
 *
 * ⚠️ **서버 문구는 바꾸지 않는다.** 대시보드가 같은 `unavailableText()`를 쓰고, 같은
 * 배가 두 화면에서 다르게 읽히면 안 된다(`#750` · `#866`). 그래서 이 검사는 서버
 * 문구를 **고정점으로 두고** 화면 문구만 본다.
 */
const HERE = dirOf(import.meta.url)

/** 서버가 내는 사유 문구 넷 — 이 화면의 등급 칸에 그대로 들어온다. */
const SERVER_TEXTS = [
  unavailableText(null),
  unavailableText('MISSING_SPEC'),
  unavailableText('NO_PARAMETERS'),
  unavailableText('CALCULATION_ERROR'),
]

/** 화면에 보이는 이 화면 전용 문구. 새로 생기면 여기에 더한다. */
function screenTexts(): string[] {
  return [
    SORT_LABEL.gaps,
    specGapFilterNotice(3),
    specGapFilterNotice(0),
    ...activeFilters({ search: '', shipType: '' } as never, true).map((f) => f.label),
  ]
}

describe('화면 어휘가 서버 어휘와 겹치지 않는다 (#2037)', () => {
  it('서버 문구에 「제원 미입력」이 있다 — 이 검사의 고정점', () => {
    expect(SERVER_TEXTS).toContain('제원 미입력')
  })

  it('화면 문구는 「제원」을 쓰지 않는다', () => {
    // 「제원 미비」와 「제원 미입력」은 세는 것이 다른데 거의 같게 읽힌다.
    expect(screenTexts().filter((text) => text.includes('제원'))).toEqual([])
  })

  it('화면 문구와 서버 문구가 같은 말이 아니다', () => {
    const collisions = screenTexts().filter((text) =>
      SERVER_TEXTS.some((server) => text.includes(server) || server.includes(text)),
    )
    expect(collisions).toEqual([])
  })

  it('칩·필터·정렬이 한 낱말로 묶여 있다 — 셋이 갈리면 같은 것을 세는지 알 수 없다', () => {
    // `#1424`가 정렬·필터를 같은 판정으로 묶었다. 말도 같아야 그 사실이 화면에서 읽힌다.
    for (const text of screenTexts()) {
      expect(text).toMatch(/입력/)
    }
  })

  it('판정 자체는 바꾸지 않았다 — 세는 항목 셋이 그대로다', () => {
    // 문구만 바꾸는 이슈였다. 항목이 늘거나 줄면 이 검사가 먼저 붉어진다.
    const source = readFileSync(join(HERE, 'listRules.ts'), 'utf8')
    const checklist = source.slice(source.indexOf('function specChecklist'))
    for (const key of ["key: 'capacity'", "key: 'referenceSpeed'", "key: 'referenceFoc'"]) {
      expect(checklist).toContain(key)
    }
  })
})
