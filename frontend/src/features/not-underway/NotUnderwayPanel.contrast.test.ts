/**
 * 정박 기록 버튼의 hover가 글자를 지우지 않는다 (`#1654`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 화면 회귀 테스트)
 *
 * ## 무엇이 깨져 있었나
 *
 * 공통 hover 규칙이 테두리 버튼과 **채움 버튼(`.nu__submit`)을 함께** 묶어, 글자를
 * `--color-link`로 바꿨다. 그 버튼의 면은 `--semantic-primary`이고 링크색도 같은
 * 계열이라 — **마우스를 올리면 글자가 배경과 같은 색이 됐다.** 저장 버튼의 제목과
 * 동작을 읽을 수 없었다(`DESIGN_SYSTEM §14`).
 *
 * ## 왜 CSS를 문자열로 읽는가
 *
 * jsdom은 cascade를 계산하지 않아 `getComputedStyle`로는 이 결함이 드러나지 않는다.
 * 규칙 자체를 읽어 **어떤 선택자가 무엇을 바꾸는지**를 본다 — 저장소의 다른 스타일
 * 동기화 검사(`styles/*.sync.test.ts`)와 같은 방식이다.
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * ⚠️ **주석을 걷고 읽는다** (`#2061`). 이 검사들은 CSS를 문자열로 보므로, 설명문에 적힌
 * 선택자·토큰 이름이 **선언으로 읽힌다.** 실제로 `#2061`에서 두 번 밟았다 — 주석의
 * `--color-link` 한 마디가 「채움 버튼이 링크색을 건다」로 잡혔고, 공통 hover의 이름을
 * 주석에 적어 둔 탓에 **그 규칙을 지워도 검사가 초록**이었다.
 */
const css = readFileSync(join(__dirname, 'NotUnderwayPanel.css'), 'utf-8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

/** 이 화면의 공통 hover 규칙 (`#2061`에서 자손 선택자 셋을 이 한 줄로 내렸다). */
const SHARED_HOVER = '.nu__button:hover'

/** 그 선택자를 포함하는 규칙 블록의 본문. */
function ruleFor(selector: string): string {
  const index = css.indexOf(selector)
  expect(index, `${selector} 규칙이 없다`).toBeGreaterThan(-1)
  const open = css.indexOf('{', index)
  return css.slice(open + 1, css.indexOf('}', open))
}

describe('정박 기록 버튼의 hover (#1654)', () => {
  it('채움 버튼의 hover는 글자색을 링크색으로 바꾸지 않는다', () => {
    // 이것이 이 결함의 본체다 — 면이 primary인데 글자도 primary 계열이 됐다.
    const hover = ruleFor('.nu__submit:hover')
    expect(hover).not.toMatch(/--color-link/)
  })

  it('채움 버튼의 hover는 면을 바꾼다 — 저장소의 다른 채움 버튼과 같은 방식', () => {
    expect(ruleFor('.nu__submit:hover')).toMatch(/background:\s*var\(--color-primary-hover\)/)
  })

  it('공통 hover 규칙에 채움 버튼이 들어 있지 않다', () => {
    /*
     * 선택자 목록에 `.nu__submit:hover`가 다시 끼면 같은 결함이 돌아온다 —
     * 뒤에 오는 규칙이 이기더라도 `color`를 함께 적으면 다시 지워진다.
     *
     * ⚠️ 종전 기준점은 `.nu__toggle:hover`였다. `#2061`이 공통 hover를 `.nu__button:hover`
     * 한 줄로 내리면서 그 문자열이 **사라졌고**, `indexOf`가 `-1`을 내 `slice`가 빈 문자열이
     * 되면서 이 검사가 **조용히 통과**했다 — 없는 자리를 보며 초록을 내고 있었다. 기준점이
     * 없으면 **먼저 실패**하게 한다.
     */
    const at = css.indexOf(SHARED_HOVER)
    expect(at, `${SHARED_HOVER} 규칙이 없다 — 공통 hover의 이름이 바뀌었으면 여기도 따라간다`).toBeGreaterThan(-1)
    expect(css.slice(at, css.indexOf('{', at))).not.toMatch(/\.nu__submit:hover/)
  })

  it('채움 버튼의 hover가 면 위 글자색을 **스스로** 적는다 (#2061)', () => {
    /*
     * `#2061`이 공통 hover를 `.nu__button:hover`로 내리면서 채움 버튼도 그 클래스를 달았다.
     * 그래서 이제 이 줄이 **없으면** 공통 hover의 링크색이 그대로 닿아 `#1654`가 돌아온다 —
     * 종전에는 「선택자 목록에서 빼는」 방식이라 이 선언이 없어도 무사했다.
     */
    expect(ruleFor('.nu__submit:hover')).toMatch(/color:\s*var\(--color-on-primary\)/)
  })

  it('위험 동작의 hover가 공통 hover **뒤에** 온다 (#2061)', () => {
    /*
     * 둘은 특이도가 같다(`0-2-0`). 같을 때는 **소스 순서**가 판정하므로, 위험 규칙을 위로
     * 옮기면 구간 삭제 버튼의 hover가 다시 기본 파랑이 된다 — 특이도만 보는 검사
     * (`styles/variantWins.sync.test.ts`)는 이 경우를 잡지 못한다.
     */
    const shared = css.indexOf(SHARED_HOVER)
    const danger = css.indexOf('.nu__danger:hover')
    expect(shared, `${SHARED_HOVER} 규칙이 없다`).toBeGreaterThan(-1)
    expect(danger, '.nu__danger:hover 규칙이 없다').toBeGreaterThan(-1)
    expect(danger).toBeGreaterThan(shared)
  })

  it('면 위 글자는 `--color-on-primary`를 쓴다', () => {
    // `--surface-card`는 라이트에서 결과가 같지만 **면 위 글자라는 뜻을 담지 않는다**.
    expect(ruleFor('.nu__submit {')).toMatch(/color:\s*var\(--color-on-primary\)/)
  })
})
