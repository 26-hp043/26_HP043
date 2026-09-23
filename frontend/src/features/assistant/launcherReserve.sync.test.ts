/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 런처가 가리는 자리를 셸이 비워 두는지 (#1375).
 *
 * ## 왜 소스로 보나
 *
 * jsdom은 레이아웃을 계산하지 않는다 — `position: fixed` 요소가 무엇을 덮는지
 * 렌더 검사로는 알 수 없다. 그래서 **두 파일이 서로를 가리키고 있는지**만 본다.
 * `deadCss.test.ts`·`a11yWiring.test.ts`가 같은 이유로 소스를 읽는다.
 *
 * ## 무엇이 깨지면 잡히나
 *
 * 이 규칙은 **한쪽만 지워도 조용히 무력해진다.** 선언을 지우면 폴백 `0px`이 걸려
 * 여백이 사라지고, 소비를 지우면 선언이 아무 데도 쓰이지 않는다. 둘 다 화면이
 * 깨지지 않으므로 눈으로도 기존 검사로도 드러나지 않는다 — `#1292`의 사본과
 * 같은 유형이다.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))
const LAUNCHER_CSS = join(HERE, 'AssistantOverlay.css')
const SHELL_CSS = join(HERE, '..', '..', 'layout', 'AppShell.css')

const NAME = '--assistant-launcher-reserve'

/** 주석 안의 언급이 근거가 되지 않게 걷어낸다 — `deadCss.test.ts`와 같은 이유다. */
function code(path: string): string {
  return readFileSync(path, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
}

describe('어시스턴트 런처가 본문 마지막 줄을 가리지 않는다 (#1375)', () => {
  it('런처 쪽이 예약 폭을 선언한다', () => {
    expect(
      new RegExp(`${NAME}\\s*:`).test(code(LAUNCHER_CSS)),
      `${NAME} 선언이 AssistantOverlay.css에 없습니다 — 값은 런처를 아는 파일이 갖습니다.`,
    ).toBe(true)
  })

  it('셸이 그 값을 아래쪽 여백에 쓴다', () => {
    const shell = code(SHELL_CSS)
    expect(
      new RegExp(`padding-block-end:[^;]*var\\(${NAME}`).test(shell),
      `AppShell.css가 ${NAME}를 padding-block-end에 쓰지 않습니다.`,
    ).toBe(true)
  })

  it('⚠️ 예약 폭을 런처가 쓰는 값들로 조립한다 — 숫자를 새로 적지 않는다', () => {
    /*
     * `§0.2`상 새 디자인 토큰은 Figma 소관이고, 이 파일 머리주석이 「기존 값만
     * 조합했다」를 규칙으로 적는다. 생짜 높이를 적으면 런처가 바뀔 때 갈린다.
     */
    // `calc()` 안에 `var()`가 중첩되므로 **선언 끝(`;`)까지** 통째로 떼어 낸다.
    // 괄호를 세는 정규식은 중첩에서 조용히 앞부분만 잡는다 — 실제로 한 번 밟았다.
    const decl = /--assistant-launcher-reserve:\s*calc\(([\s\S]*?)\);/.exec(code(LAUNCHER_CSS))
    expect(decl, '예약 폭이 calc()로 조립돼 있지 않습니다').not.toBeNull()
    for (const token of ['--space-8', '--font-size-label', '--line-height-label']) {
      expect(decl![1], `${token}가 식에 없습니다`).toContain(token)
    }
  })
})

/**
 * 패널이 열리면 넓은 화면에서 셸이 오른쪽을 비운다 (#1613 · R21).
 *
 * jsdom은 미디어 쿼리 · 고정 배치를 계산하지 않으므로 위와 같이 **서로를 가리키는지**를 본다.
 * 패널 폭과 비우는 폭이 **같은 변수**여야 한다 — 한쪽만 숫자로 바꾸면 틈이 생기거나 다시 덮인다.
 */
describe('어시스턴트 패널이 넓은 화면에서 본문을 덮지 않는다 (#1613)', () => {
  const SHELL_TSX = join(HERE, '..', '..', 'layout', 'AppShell.tsx')
  const css = () => code(LAUNCHER_CSS)

  it('패널 폭과 셸이 비우는 폭이 같은 변수다', () => {
    expect(css()).toMatch(/--assistant-panel-width\s*:/)
    expect(css()).toMatch(/\.assistant\s*\{[^}]*width:\s*min\(var\(--assistant-panel-width\)/)
    /*
     * ⚠️ 전환점 **값**은 여기서 보지 않는다 (#1818). 이 검사가 잠그는 것은 「패널 폭과
     * 셸이 비우는 폭이 같은 변수인가」이고, 값이 얼마여야 하는지는
     * `layout.sync.test.ts`가 `#1788`의 목록 최소 폭에서 산술로 본다. 두 검사가 같은
     * 숫자를 들면 한쪽만 고쳐도 조용히 갈린다.
     */
    const rule = /@media\s*\(min-width:\s*\d+px\)\s*\{\s*\.app-shell--assistant-open\s*\{([^}]*)\}/.exec(css())
    expect(rule, '.app-shell--assistant-open 미디어 규칙이 없습니다').not.toBeNull()
    expect(rule![1]).toMatch(/padding-inline-end:[^;]*var\(--assistant-panel-width\)/)
  })

  it('셸이 패널 열림을 받아 그 클래스를 붙인다', () => {
    const shell = readFileSync(SHELL_TSX, 'utf-8')
    expect(shell).toMatch(/onOpenChange=\{setAssistantOpen\}/)
    expect(shell).toMatch(/assistantOpen \? 'app-shell app-shell--assistant-open'/)
  })
})
