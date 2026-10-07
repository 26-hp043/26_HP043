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
 * 빈 대화에서 입력칸이 패널 밖으로 밀려나지 않는다 (#2158).
 *
 * 패널 높이는 굳어 있고 빈 대화의 내용물은 그보다 길다. 소개 그림이 줄지 못하면 넘친
 * 만큼 맨 아래 입력 줄이 화면 밖으로 나간다 — 패널은 열렸는데 물어볼 칸이 없다
 * (실측 1440×900: 패널 바닥 876, 입력 줄 926~959).
 *
 * 세 선언이 그것을 막는다. 하나를 되돌려도 jsdom 검사는 전부 통과한다.
 */
describe('빈 대화에서 입력 줄이 패널 안에 남는다 (#2158)', () => {
  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, '\\$&')
    const match = new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(CSS)
    expect(match, `${selector} 규칙이 없습니다`).not.toBeNull()
    return match![2]
  }

  it('소개 그림이 줄 수 있다 — 높이를 굳히지 않고 flex-basis로만 준다', () => {
    const art = rule('.assistant__intro-art')
    expect(/(^|[\s;])height\s*:/.test(art), '`height`를 적으면 그림이 줄지 않습니다.').toBe(false)
    expect(/flex\s*:\s*0\s+1\s+var\(--assistant-intro-art-height\)/.test(art)).toBe(true)
  })

  it('소개 그림의 바닥이 제 높이보다 낮다', () => {
    const px = (name: string): number => {
      const match = new RegExp(`${name}\\s*:\\s*(\\d+)px`).exec(CSS)
      expect(match, `${name} 선언이 없습니다`).not.toBeNull()
      return Number(match![1])
    }
    expect(/min-height\s*:\s*var\(--assistant-intro-art-min-height\)/.test(rule('.assistant__intro-art'))).toBe(true)
    expect(px('--assistant-intro-art-min-height')).toBeLessThan(px('--assistant-intro-art-height'))
  })

  it('머리줄과 입력 줄 사이가 스크롤된다 — min-height: 0 + overflow-y: auto', () => {
    const body = rule('.assistant__body')
    expect(/min-height\s*:\s*0\s*;/.test(body), '없으면 이 영역이 줄지 않아 패널이 넘칩니다.').toBe(true)
    expect(/overflow-y\s*:\s*auto/.test(body)).toBe(true)
    expect(/flex\s*:\s*1\s*;/.test(body)).toBe(true)
  })

  it('대화 영역 최소 높이는 120 그대로다 — 빈 대화에서만 내용 높이를 쓴다', () => {
    expect(/min-height\s*:\s*120px/.test(rule('.assistant__log'))).toBe(true)
    const empty = rule('.assistant__log:has(> .assistant__empty)')
    expect(/flex\s*:\s*none/.test(empty)).toBe(true)
    expect(/min-height\s*:\s*0\s*;/.test(empty)).toBe(true)
  })

  it('남는 폭을 받는 것은 입력을 감싼 .field다', () => {
    expect(/flex\s*:\s*1\s*;/.test(rule('.assistant__form > .field'))).toBe(true)
  })
})

/**
 * 패널이 본문을 덮지 않는다 — 오른쪽에 붙는 패널 (#2322 · 10/7 디자인 결정).
 *
 * 종전에는 떠 있는 창이라 넓은 화면(1640 · 선박 관리 1756)에서만 셸이 비켰다. 패널이 화면
 * 오른쪽에 위아래로 붙으면서 **1280 이상 모든 화면에서** 셸이 패널 폭만큼 비킨다. 그 폭에서
 * 선박 관리 목록(최소 760)이 본문에 다 들어가지 않을 수 있으므로, 목록은 카드 안에서 가로로
 * 스크롤한다(`#1788`) — 아래 두 번째 검사가 그 넘침 처리가 풀리지 않게 잠근다.
 */
describe('패널이 본문을 덮지 않는다 (#2322)', () => {
  it('1280 이상에서 셸이 패널 폭만큼 비킨다', () => {
    expect(
      /@media\s*\(min-width:\s*1280px\)\s*\{[\s\S]*?\.app-shell--assistant-open[^{]*\{\s*padding-inline-end:\s*var\(--assistant-panel-width\)/.test(CSS),
    ).toBe(true)
  })

  it('선박 관리 목록의 넘침 처리는 패널이 열려 있으면 풀리지 않는다', () => {
    const vmCss = readFileSync(join(HERE, '..', 'vessel-management', 'VesselManagement.css'), 'utf-8')
    const visible = vmCss.match(/[^{}]*\{[^{}]*overflow:\s*visible[^{}]*\}/g) ?? []
    for (const block of visible.filter((b) => b.includes('.vm__list-wrap'))) {
      expect(block, '패널이 열린 셸에서 목록 넘침을 풀면 페이지가 가로로 밀린다(#1788)').toContain(
        ':not(.app-shell--assistant-open)',
      )
    }
  })
})
