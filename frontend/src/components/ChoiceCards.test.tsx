// @vitest-environment jsdom
import '../test/renderSetup'

import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChoiceCards, type ChoiceOption } from './ChoiceCards'

type Mode = 'A' | 'B' | 'C'

const OPTIONS: ReadonlyArray<ChoiceOption<Mode>> = [
  { value: 'A', label: '총량', description: '전체를 그대로 넣습니다' },
  { value: 'B', label: '하루 × 항해일', description: '하루 값에 항해일을 곱합니다' },
  { value: 'C', label: '선박 제원에서', description: '등록 값을 씁니다', disabled: true, reasonId: 'why' },
]

function Harness() {
  const [value, setValue] = useState<Mode>('A')
  return (
    <>
      <button type="button">앞</button>
      <ChoiceCards name="mode" legend="연료 입력 방식" options={OPTIONS} value={value} onChange={setValue}>
        <p id="why">선박을 먼저 고르세요.</p>
      </ChoiceCards>
      <output data-testid="value">{value}</output>
    </>
  )
}

/** `aria-describedby`가 가리키는 글을 이어 붙인다 — jest-dom 없이 설명을 읽는다. */
function description(el: HTMLElement): string {
  return (el.getAttribute('aria-describedby') ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
}

/*
 * jsdom에는 `CSS.escape`가 없다. user-event가 라디오 화살표 이동(`walkRadio`)에서 그것으로
 * 같은 `name`의 형제를 찾으므로, 이 파일 안에서만 최소 구현을 둔다(이름에 특수문자 없음).
 */
const css = globalThis as { CSS?: { escape?: (value: string) => string } }
css.CSS = { ...css.CSS, escape: css.CSS?.escape ?? ((value: string) => value.replace(/[^\w-]/g, '\\$&')) }

describe('선택 카드 (#2201 · DESIGN_SYSTEM §8.4)', () => {
  it('라디오의 이름은 선택지 이름뿐이고, 풀이는 설명으로 잇는다', () => {
    render(<Harness />)
    const radio = screen.getByRole('radio', { name: '하루 × 항해일' })
    expect(description(radio)).toBe('하루 값에 항해일을 곱합니다')
    // 그룹 이름은 legend
    expect(screen.getByRole('group', { name: '연료 입력 방식' })).toBeTruthy()
  })

  it('고를 수 없는 선택지는 풀이 뒤에 사유를 잇는다 (§14 비활성의 사유)', () => {
    render(<Harness />)
    const radio = screen.getByRole('radio', { name: '선박 제원에서' }) as HTMLInputElement
    expect(radio.disabled).toBe(true)
    expect(description(radio)).toBe('등록 값을 씁니다 선박을 먼저 고르세요.')
  })

  it('키보드만으로 고르고 바꾼다 — Tab으로 들어가 화살표로 옮긴다', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    screen.getByRole('button', { name: '앞' }).focus()

    await user.tab()
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: '총량' }))

    await user.keyboard('{ArrowDown}')
    expect((screen.getByRole('radio', { name: '하루 × 항해일' }) as HTMLInputElement).checked).toBe(true)
    expect(screen.getByTestId('value').textContent).toBe('B')
  })

  it('비활성 선택지는 눌러도 고르지 않는다', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByText('선박 제원에서'))
    expect(screen.getByTestId('value').textContent).toBe('A')
  })
})
