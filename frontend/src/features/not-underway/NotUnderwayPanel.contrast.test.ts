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

const css = readFileSync(join(__dirname, 'NotUnderwayPanel.css'), 'utf-8')

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
     */
    const shared = css.slice(css.indexOf('.nu__toggle:hover'), css.indexOf('{', css.indexOf('.nu__toggle:hover')))
    expect(shared).not.toMatch(/\.nu__submit:hover/)
  })

  it('면 위 글자는 `--color-on-primary`를 쓴다', () => {
    // `--surface-card`는 라이트에서 결과가 같지만 **면 위 글자라는 뜻을 담지 않는다**.
    expect(ruleFor('.nu__submit {')).toMatch(/color:\s*var\(--color-on-primary\)/)
  })
})
