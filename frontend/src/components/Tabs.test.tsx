// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { Tabs, type TabDef } from './Tabs'

/**
 * 탭 — `DESIGN_SYSTEM §8` (#1772 · #1774).
 *
 * 이 부품이 **낭독 배선을 강제한다**는 것이 `§8`의 조항이므로, 그 배선을 여기서 잠근다 —
 * 호출부마다 적게 두면 빠진 자리가 생기고 **그 자리는 화면이 깨지지 않아 발견되지 않는다**
 * (`§8.4`가 `Field`로 닫은 것과 같은 이유).
 */

let renders: Record<string, number> = {}

function items(): TabDef[] {
  return ['가', '나', '다'].map((label) => ({
    id: label,
    label,
    render: () => {
      renders[label] = (renders[label] ?? 0) + 1
      return <input data-testid={`in-${label}`} defaultValue="" />
    },
  }))
}

/** 자리를 밖이 갖는다 — 실제 화면에서는 주소가 갖는다(`§8`). */
function Harness({ start = '가' }: { start?: string }) {
  const [current, setCurrent] = useState(start)
  return <Tabs label="묶음" items={items()} current={current} onSelect={setCurrent} />
}

function setup(start?: string) {
  renders = {}
  render(<Harness start={start} />)
}

describe('탭의 낭독 배선 (#1772)', () => {
  it('탭 줄과 탭·패널이 서로를 가리킨다', () => {
    setup()
    const list = screen.getByRole('tablist', { name: '묶음' })
    expect(list).toBeTruthy()

    const tab = screen.getByRole('tab', { name: '가' })
    const panel = screen.getByRole('tabpanel')
    expect(tab.getAttribute('aria-controls')).toBe(panel.id)
    expect(panel.getAttribute('aria-labelledby')).toBe(tab.id)
    expect(tab.getAttribute('aria-selected')).toBe('true')
  })

  it('roving tabindex — Tab 키로 탭 줄에 한 번만 들어온다', () => {
    setup()
    const [first, second, third] = screen.getAllByRole('tab')
    expect(first.getAttribute('tabindex')).toBe('0')
    expect(second.getAttribute('tabindex')).toBe('-1')
    expect(third.getAttribute('tabindex')).toBe('-1')
  })

  it('좌우 화살표가 초점과 선택을 함께 옮기고, 끝에서 돌아온다', () => {
    setup()
    const list = screen.getByRole('tablist', { name: '묶음' })

    fireEvent.keyDown(list, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: '나' }).getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: '나' }))

    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    // 첫 탭에서 왼쪽 → 마지막으로 돈다.
    expect(screen.getByRole('tab', { name: '다' }).getAttribute('aria-selected')).toBe('true')
  })

  it('Home · End가 양 끝으로 간다', () => {
    setup()
    const list = screen.getByRole('tablist', { name: '묶음' })

    fireEvent.keyDown(list, { key: 'End' })
    expect(screen.getByRole('tab', { name: '다' }).getAttribute('aria-selected')).toBe('true')

    fireEvent.keyDown(list, { key: 'Home' })
    expect(screen.getByRole('tab', { name: '가' }).getAttribute('aria-selected')).toBe('true')
  })

  it('다른 키는 가로채지 않는다', () => {
    setup()
    const list = screen.getByRole('tablist', { name: '묶음' })
    fireEvent.keyDown(list, { key: 'a' })
    expect(screen.getByRole('tab', { name: '가' }).getAttribute('aria-selected')).toBe('true')
  })
})

describe('열기 전에는 마운트하지 않는다 (#1772)', () => {
  it('열지 않은 탭은 그리지 않는다 — 그 탭의 조회도 나가지 않는다', () => {
    setup()
    expect(renders['가']).toBe(1)
    expect(renders['나']).toBeUndefined()
    expect(screen.queryByTestId('in-나')).toBeNull()
  })

  it('한 번 연 탭은 감추되 지우지 않는다 — 쓰던 입력이 남는다', () => {
    setup()
    fireEvent.change(screen.getByTestId('in-가'), { target: { value: '쓰던 값' } })

    fireEvent.click(screen.getByRole('tab', { name: '나' }))
    // 감춘다 — 지우지 않는다.
    const hidden = screen.getByTestId('in-가')
    expect(hidden.closest('[hidden]')).not.toBeNull()
    expect((hidden as HTMLInputElement).value).toBe('쓰던 값')

    fireEvent.click(screen.getByRole('tab', { name: '가' }))
    expect((screen.getByTestId('in-가') as HTMLInputElement).value).toBe('쓰던 값')
  })

  it('보이는 패널은 언제나 하나다', () => {
    setup()
    fireEvent.click(screen.getByRole('tab', { name: '나' }))
    fireEvent.click(screen.getByRole('tab', { name: '다' }))
    // `getAllByRole('tabpanel')`은 `hidden`을 세지 않는다.
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1)
  })

  it('자리를 스스로 갖지 않는다 — 고르면 밖에 알린다', () => {
    const onSelect = vi.fn()
    renders = {}
    render(<Tabs label="묶음" items={items()} current="가" onSelect={onSelect} />)

    fireEvent.click(screen.getByRole('tab', { name: '나' }))

    expect(onSelect).toHaveBeenCalledWith('나')
    // 밖이 `current`를 바꾸지 않았으므로 화면은 그대로다.
    expect(screen.getByRole('tab', { name: '가' }).getAttribute('aria-selected')).toBe('true')
  })
})
