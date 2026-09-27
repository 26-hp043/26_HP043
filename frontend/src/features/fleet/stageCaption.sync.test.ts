import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 지도 아래 문구 줄이 열린 패널 밑에 깔리지 않는다 (#1871).
 *
 * 패널은 무대(`.fleet__stage`)의 위아래를 다 차지하고, 무대 안에는 캔버스 아래 문구
 * 줄도 들어 있다. 비켜 두는 규칙이 빠지면 「다시 시도」가 패널 밑에서 눌리지 않는데
 * **화면은 깨지지 않아** 검사가 없으면 조용히 되돌아간다(jsdom은 배치를 계산하지 않는다).
 */
const css = readFileSync(join(import.meta.dirname, 'FleetDashboard.css'), 'utf8')

function rule(selectorHead: string): { selectors: string; body: string } {
  const at = css.indexOf(selectorHead)
  expect(at, `${selectorHead} 규칙이 있다`).toBeGreaterThan(-1)
  const open = css.indexOf('{', at)
  return { selectors: css.slice(at, open), body: css.slice(open, css.indexOf('}', open)) }
}

describe('열린 패널 옆으로 지도 아래 문구 줄을 비킨다 (#1871)', () => {
  const { selectors, body } = rule('.fleet__stage--panel-open .fleetmap__missing')

  it('결측·항로선 실패 줄 · 읽는 법 · 경로망 출처 · 지도 텍스트 정보를 함께 비킨다', () => {
    // 포함 검사로는 `.fleetmap__hintX` 같은 오타가 빠져나간다 — 쉼표로 나눠 정확히 견준다.
    const list = selectors.split(',').map((s) => s.trim())
    expect(list).toContain('.fleet__stage--panel-open .fleetmap__missing')
    expect(list).toContain('.fleet__stage--panel-open .fleetmap__hint')
    expect(list).toContain('.fleet__stage--panel-open .map-alternative')
    expect(list).toContain('.fleet__stage--panel-open .route-source')
  })

  it('들여쓰기 폭이 패널의 자리·폭 식과 같다', () => {
    const panel = rule('.fleet__panel {').body
    expect(panel).toMatch(/inset-inline-start:\s*var\(--spacing-md\)/)
    expect(panel).toMatch(/inline-size:\s*min\(360px,\s*calc\(100% - var\(--spacing-xl\)\)\)/)
    expect(body.replace(/\s+/g, ' ')).toMatch(
      /padding-inline-start: calc\( var\(--spacing-md\) \+ min\(360px, calc\(100% - var\(--spacing-xl\)\)\) \+ var\(--spacing-md\) \)/,
    )
  })
})
