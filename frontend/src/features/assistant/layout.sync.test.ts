/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 어시스턴트 패널의 자리 배분 가드 (#1818).
 *
 * ## 왜 소스로 보나
 *
 * jsdom은 레이아웃도 미디어 쿼리도 계산하지 않는다 — 두 규칙 다 **화면이 깨지지
 * 않으면서** 조용히 무력해지는 종류다. `launcherReserve.sync.test.ts`가 같은 이유로
 * 소스를 읽는다.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))
const CSS_PATH = join(HERE, 'AssistantOverlay.css')
const VM_GUARD = join(HERE, '..', 'vessel-management', 'layout.sync.test.ts')

/** 주석 안의 언급이 근거가 되지 않게 걷어낸다 — `deadCss.test.ts`와 같은 이유다. */
function code(path: string): string {
  return readFileSync(path, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
}
const CSS = code(CSS_PATH)

/**
 * 「답이 아닌 것」 셋을 같은 모양으로 두지 않는다 (`DESIGN_SYSTEM §8.5` 🔒 머리 문장).
 *
 * 2026-09-17 확정 ⓓ가 **면책에서 줄무늬를 걷었다.** 그런데 배경과 글자색은 그대로
 * 같아서, 로그가 바닥까지 차 **버린 답이 면책 바로 위에 붙으면** 둘을 가르는 것이
 * 줄무늬 4px 하나뿐이었다. 확정이 「떨어져 있을 것」을 전제한 자리다.
 *
 * ⚠️ 면책에서 **면을 걷는 것**이 그 해법이고, 이 검사는 면이 돌아오는 것을 막는다.
 * 선언 한 줄을 되돌려도 화면은 멀쩡해 보이므로 눈으로는 드러나지 않는다.
 */
describe('면책이 버린 답과 같은 면을 쓰지 않는다 (§8.5 · #1818)', () => {
  function rule(selector: string): string {
    const match = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(CSS)
    expect(match, `${selector} 규칙이 없습니다`).not.toBeNull()
    return match![1]
  }

  it('면책에 background 선언이 없다', () => {
    expect(
      /background/.test(rule('.assistant__disclaimer')),
      '면책이 다시 면을 얻었습니다 — 버린 답과 붙으면 한 덩어리로 읽힙니다.',
    ).toBe(false)
  })

  it('버린 답은 면을 그대로 쓴다 — 걷는 쪽은 면책이다', () => {
    expect(/background/.test(rule('.assistant__turn--assistant'))).toBe(true)
  })

  it('면책이 로그의 끝을 경계로 세운다', () => {
    expect(
      /border-(block-start|top)\s*:/.test(rule('.assistant__disclaimer')),
      '면책에 경계선이 없으면 로그 안과 밖이 갈리지 않습니다.',
    ).toBe(true)
  })
})

/**
 * 패널이 본문을 덮지 않는 폭이 **선박 관리 목록을 담을 만큼** 남기는지 (#1818 · #1788).
 *
 * 종전 값 `1366`은 본문에 `650px`만 남겼다 — 목록 최소 폭 `890`에 한참 못 미친다.
 * 그 파일 주석이 「약 900px 남는다」고 적고 있었는데 **사이드바와 여백을 빼지 않은
 * 계산**이었다.
 *
 * ⚠️ 이 검사는 **숫자를 새로 적지 않는다** — `890`은 `#1788`의 가드에서, 패널 폭은
 * CSS 변수에서 읽는다. 한쪽을 바꾸면 여기서 걸린다.
 */
describe('패널을 비우는 폭이 목록 최소 폭을 남긴다 (#1818 · #1788)', () => {
  /** `#1788`이 브라우저에서 잰 목록 최소 폭. 그 가드가 소유한다. */
  const LIST_MIN = (() => {
    const match = /const MEASURED_MIN = (\d+)/.exec(readFileSync(VM_GUARD, 'utf-8'))
    expect(match, '선박 관리 가드에서 MEASURED_MIN을 읽지 못했습니다').not.toBeNull()
    return Number(match![1])
  })()

  /** 패널 폭. 셸이 비우는 폭과 **같은 변수**여야 한다(`launcherReserve.sync.test.ts`). */
  const PANEL = (() => {
    const match = /--assistant-panel-width:\s*(\d+)px/.exec(CSS)
    expect(match, '패널 폭 선언을 읽지 못했습니다').not.toBeNull()
    return Number(match![1])
  })()

  /*
   * 아래 셋은 브라우저에서 잰 고정분이다(1440 · 라이트 · 시연 데이터).
   * 본문 폭 = 화면 폭 − (사이드바 + 셸 여백 + 패널과 그 여백)이고,
   * 목록이 들어가는 칸은 거기서 카드 좌우 패딩만큼 더 좁다.
   */
  const SIDEBAR = 240 // --layout-sidebar-width (--grid-gnb-expanded)
  const SHELL_GUTTERS = 48 // 셸 padding 24 + 사이드바와 본문 사이 gap 24
  const CARD_PADDING = 34 // 목록 카드 좌우 패딩 16 + 테두리 1, 양쪽
  const RESERVE = 24 * 2 + PANEL // --shell-gutter * 2 + 패널 폭

  const NEEDED = LIST_MIN + CARD_PADDING + SHELL_GUTTERS + SIDEBAR + RESERVE

  it('산술이 1640으로 떨어진다 — 고른 값이 아니다', () => {
    expect(NEEDED).toBe(1640)
  })

  it('전환점이 그 폭 아래로 내려가지 않는다', () => {
    const match = /@media\s*\(min-width:\s*(\d+)px\)\s*\{\s*\.app-shell--assistant-open/.exec(CSS)
    expect(match, '.app-shell--assistant-open 미디어 규칙이 없습니다').not.toBeNull()
    expect(
      Number(match![1]),
      `전환점이 ${NEEDED} 밑이면 본문이 선박 관리 목록(${LIST_MIN})을 담지 못해 목록이 가로로 스크롤됩니다.`,
    ).toBeGreaterThanOrEqual(NEEDED)
  })
})
