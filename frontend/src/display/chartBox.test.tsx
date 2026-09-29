// @vitest-environment jsdom
import '../test/renderSetup'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { CHART_FALLBACK_WIDTH, useChartWidth } from './chartBox'

/**
 * 차트가 **배율을 타지 않는지** 본다 (`DESIGN_SYSTEM §9.1` · `#2038`).
 *
 * ## 「선언이 있는가」가 아니라 「실제로 몇인가」를 본다
 *
 * `#1770` · `#2015`가 같은 자리에서 걸렸다 — 규칙은 코드에 있는데 **이기지 못했고**,
 * 가드는 문구만 보고 초록을 냈다. 그래서 이 가드는 `viewBox` 문자열이 있는지가 아니라
 * **잰 폭과 뷰박스 폭이 같은지**를 본다. 둘이 같으면 `1칸 = 1 CSS px`이고, 그때만
 * `§9`가 적은 px가 화면의 px가 된다.
 *
 * ## jsdom은 배치를 하지 않는다
 *
 * `getBoundingClientRect()`가 늘 0을 돌려주므로 **폭을 주입한다.** 브라우저에서 잰
 * 값은 `#2038` 본문의 표에 있다(1920에서 배율 `2.19×` → `1.0×`).
 */

/** 관측 중인 콜백. 폭을 바꾼 뒤 이것을 불러 브라우저의 재관측을 흉내 낸다. */
let observed: (() => void)[] = []

function stubLayout(width: number): void {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ width, height: 0, top: 0, left: 0, right: width, bottom: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect,
  )
}

class FakeResizeObserver {
  // 매개변수 속성(`private readonly callback`)은 `erasableSyntaxOnly`가 막는다 — 타입만
  // 지워서는 사라지지 않는 문법이라 런타임 의미가 달라진다.
  private readonly callback: () => void

  constructor(callback: () => void) {
    this.callback = callback
  }

  observe(): void {
    observed.push(this.callback)
  }

  disconnect(): void {
    observed = observed.filter((c) => c !== this.callback)
  }

  unobserve(): void {}
}

const VIEW_H = 200

function Chart() {
  const { ref, width } = useChartWidth()
  return (
    <div ref={ref}>
      <svg data-testid="canvas" width={width} height={VIEW_H} viewBox={`0 0 ${width} ${VIEW_H}`} />
    </div>
  )
}

function box(): { w: number; h: number } {
  const viewBox = screen.getByTestId('canvas').getAttribute('viewBox') ?? ''
  const [, , w, h] = viewBox.split(' ').map(Number)
  return { w, h }
}

afterEach(() => {
  observed = []
  vi.restoreAllMocks()
})

describe('차트는 배율을 타지 않는다 (#2038)', () => {
  it('뷰박스 폭이 잰 폭과 같다 — 배율 1.0×', () => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    stubLayout(1574)
    render(<Chart />)
    expect(box().w).toBe(1574)
  })

  it('폭이 바뀌어도 높이는 그대로다', () => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    stubLayout(550)
    render(<Chart />)
    expect(box()).toEqual({ w: 550, h: VIEW_H })

    // 창을 넓힌다 — 종전에는 이때 높이까지 2.9배가 됐다.
    stubLayout(1574)
    act(() => observed.forEach((c) => c()))
    expect(box()).toEqual({ w: 1574, h: VIEW_H })
  })

  it('네 폭 모두에서 배율이 1이다 — #2038 실측과 같은 폭', () => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    stubLayout(550)
    render(<Chart />)
    for (const width of [550, 930, 1094, 1574]) {
      stubLayout(width)
      act(() => observed.forEach((c) => c()))
      expect(box().w / width).toBe(1)
    }
  })

  it('폭 0은 받지 않는다 — 감춰진 탭에서 마운트되면 0이 온다', () => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    stubLayout(0)
    render(<Chart />)
    // 0을 넣었다면 뷰박스가 무너져 선이 한 점으로 모인다.
    expect(box().w).toBe(CHART_FALLBACK_WIDTH)
  })

  it('ResizeObserver가 없어도 그린다 — 마운트 때 한 번은 잰다', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    stubLayout(930)
    render(<Chart />)
    expect(box().w).toBe(930)
  })
})
