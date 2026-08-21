// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { GradePatternDefs } from './GradePatternDefs'

/**
 * 등급 패턴 규격 (`DESIGN_SYSTEM §15.1` 「공통 규격 🔒」 · `#485` ⑦⑧).
 *
 * ## 왜 이 테스트가 필요했나
 *
 * 이 파일의 주석은 *「자동 테스트로는 검증할 수 없다」*고 적고 있었고, 그것은
 * **절반만 맞다.** 패턴이 실제로 칠해지는지는 렌더 결과를 봐야 알 수 있지만,
 * **어떤 값으로 그리는지는 속성으로 읽을 수 있다.**
 *
 * 그 절반이 비어 있는 동안 굵기 넷과 E의 무늬가 규격에서 벗어났고, 시각 검증은
 * 「다섯 개가 서로 달라 보인다」로 통과시켰다 — **규격과 대조하는 눈은 없었다.**
 *
 * 여기서 고정하는 것은 §15.1이 값으로 확정한 것들이다.
 */

function defs() {
  const { container } = render(<GradePatternDefs />)
  return container
}

function pattern(container: HTMLElement, id: string) {
  const node = container.querySelector(`#${id}`)
  expect(node, `${id} 패턴이 없다`).not.toBeNull()
  return node as SVGPatternElement
}

describe('등급 패턴 — §15.1 공통 규격', () => {
  it('타일 간격은 네 등급 모두 4px다', () => {
    const container = defs()
    for (const id of ['grade-b', 'grade-c', 'grade-d', 'grade-e']) {
      const node = pattern(container, id)
      expect(node.getAttribute('width'), id).toBe('4')
      expect(node.getAttribute('height'), id).toBe('4')
      // 타일을 확대·축소하지 않고 잘라 쓴다 — `§15.1`.
      expect(node.getAttribute('patternUnits'), id).toBe('userSpaceOnUse')
    }
  })

  it('A는 정의하지 않는다 — 「패턴 없음」이 A의 식별 표시다', () => {
    expect(defs().querySelector('#grade-a')).toBeNull()
  })

  it('사선은 굵기 1.5 · 점은 r 0.9 · 격자는 굵기 1.2다', () => {
    // 눈으로 맞추면 조용히 흘러간다. 실제로 1.2 · 1.2 · 1.0으로 흘러가 있었다.
    const container = defs()
    for (const id of ['grade-b', 'grade-d']) {
      const line = pattern(container, id).querySelector('line')
      expect(line?.getAttribute('stroke-width'), id).toBe('1.5')
    }
    expect(pattern(container, 'grade-c').querySelector('circle')?.getAttribute('r')).toBe('0.9')
    for (const line of pattern(container, 'grade-e').querySelectorAll('line')) {
      expect(line.getAttribute('stroke-width')).toBe('1.2')
    }
  })

  it('B와 D는 서로 반대 방향 사선이다', () => {
    const container = defs()
    const b = pattern(container, 'grade-b').getAttribute('patternTransform')
    const d = pattern(container, 'grade-d').getAttribute('patternTransform')
    expect(b).toBe('rotate(45)')
    expect(d).toBe('rotate(135)')
    expect(b).not.toBe(d)
  })

  it('E는 격자다 — 대각선이면 D와 뒤섞인다', () => {
    /*
     * `§2.4.4`가 C·D 패턴을 교체하며 적은 이유가 이것을 요구한다.
     *
     * > 같은 색상군인 D·E에 **사선과 격자**를 나누어 군 내 구분을 강화했다
     *
     * D가 135° 사선이라 E가 대각선 X면 D를 겹친 것으로 보인다. 3색 체계에서
     * D·E는 같은 빨강 계열이라 패턴이 **유일한 구분 채널**이다.
     */
    const e = pattern(defs(), 'grade-e')
    expect(e.querySelector('path'), 'E를 path로 그리면 대각선으로 돌아간 것이다').toBeNull()

    const lines = [...e.querySelectorAll('line')].map((line) => ({
      x1: line.getAttribute('x1'),
      y1: line.getAttribute('y1'),
      x2: line.getAttribute('x2'),
      y2: line.getAttribute('y2'),
    }))
    expect(lines).toHaveLength(2)
    // 수평 한 줄 + 수직 한 줄. 어느 쪽도 대각선이 아니다.
    expect(lines).toContainEqual({ x1: '0', y1: '0', x2: '4', y2: '0' })
    expect(lines).toContainEqual({ x1: '0', y1: '0', x2: '0', y2: '4' })
  })

  it('무늬 색은 해당 등급의 bg 토큰이다 — 하드코딩 hex 금지 (§15)', () => {
    // 흰색을 박으면 다크에서 밝아진 fill 위에 흰 무늬가 얹혀 사라진다.
    const container = defs()
    for (const [id, token] of [
      ['grade-b', '--cii-b-bg'],
      ['grade-c', '--cii-c-bg'],
      ['grade-d', '--cii-d-bg'],
      ['grade-e', '--cii-e-bg'],
    ]) {
      expect(pattern(container, id).innerHTML, id).toContain(`var(${token})`)
    }
  })

  it('opacity를 쓰지 않는다 — 두 모드에서 결과가 갈린다', () => {
    expect(defs().innerHTML).not.toContain('opacity')
  })
})
