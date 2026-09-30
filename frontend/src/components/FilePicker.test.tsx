// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CHOOSE_FILE, FilePicker, NO_FILE_CHOSEN } from './FilePicker'

/**
 * CSV를 고르는 자리 (#2049).
 *
 * ## 무엇을 잠그나
 *
 * 브라우저 기본 단추를 가리는 일은 **접근성을 잃기 쉬운 변경**이다 — `display: none`을
 * 쓰면 초점을 못 받고, `<input>`을 지우면 낭독이 이름을 잃는다. 눈으로는 둘 다
 * 멀쩡해 보인다(한국어 단추가 잘 그려져 있다). 그래서 **보이지 않는 쪽**을 검사한다:
 * 입력이 남아 있는가 · 이름이 그대로인가 · 라벨이 그 입력을 가리키는가.
 */
function setup(file: File | null = null) {
  const onPick = vi.fn()
  render(
    <FilePicker id="pick" ariaLabel="적재할 CSV 파일" accept=".csv" file={file} onPick={onPick} />,
  )
  return { onPick, input: screen.getByLabelText('적재할 CSV 파일') as HTMLInputElement }
}

describe('파일 선택 (#2049)', () => {
  it('단추 글자가 한국어다 — 브라우저 UI 언어를 따르지 않는다', () => {
    setup()
    expect(screen.getByText(CHOOSE_FILE)).toBeTruthy()
    expect(CHOOSE_FILE).not.toMatch(/[A-Za-z]/)
  })

  it('⚠️ `<input type="file">`을 지우지 않는다 — 이름도 그대로다', () => {
    /*
     * 접근성 트리와 키보드 조작이 그 요소에 걸려 있다. 라벨만 그리고 입력을 없애면
     * 낭독이 「적재할 CSV 파일」을 잃고, 자바스크립트로 여는 단추만 남는다.
     */
    const { input } = setup()
    expect(input.tagName).toBe('INPUT')
    expect(input.type).toBe('file')
    expect(input.accept).toBe('.csv')
  })

  it('⚠️ 감추되 초점을 받는다 — `display: none`을 쓰지 않는다', () => {
    /*
     * jsdom은 배치를 계산하지 않으므로 **어떤 방법으로 감췄는지**를 본다.
     * `.sr-only`(화면 밖으로 잘라 두되 트리에는 남긴다)가 저장소의 방법이다.
     * `hidden` 속성이나 `display: none`이면 Tab이 닿지 않는다.
     */
    const { input } = setup()
    expect(input.className).toContain('sr-only')
    expect(input.hasAttribute('hidden')).toBe(false)
    expect(input.style.display).not.toBe('none')

    input.focus()
    expect(document.activeElement, 'Tab으로 닿지 못합니다').toBe(input)
  })

  it('라벨이 그 입력을 가리킨다 — 눌러서 열리는 것은 브라우저 기본 동작이다', () => {
    const { input } = setup()
    const label = screen.getByText(CHOOSE_FILE)
    expect(label.tagName).toBe('LABEL')
    expect(label.getAttribute('for')).toBe(input.id)
  })

  it('고르기 전 문구가 한국어다', () => {
    setup()
    expect(screen.getByText(NO_FILE_CHOSEN)).toBeTruthy()
    expect(NO_FILE_CHOSEN).not.toMatch(/[A-Za-z]/)
  })

  it('⚠️ 고른 파일 이름이 화면에 보인다', () => {
    /*
     * 종전에는 브라우저 단추 **안에만** 있었다. 단추를 가리면 「무엇을 골랐는지」가
     * 함께 사라진다 — 이 줄이 없으면 사용자는 고른 뒤에도 확인할 곳이 없다.
     */
    setup(new File(['a,b'], '규제값_2026.csv', { type: 'text/csv' }))
    expect(screen.getByText('규제값_2026.csv')).toBeTruthy()
    expect(screen.queryByText(NO_FILE_CHOSEN)).toBeNull()
  })

  it('파일 이름은 낭독에 싣지 않는다 — 같은 사실을 두 번 읽지 않는다', () => {
    setup(new File(['a'], 'x.csv'))
    expect(screen.getByText('x.csv').getAttribute('aria-hidden')).toBe('true')
  })

  it('고르면 그 파일을 넘긴다', () => {
    const { onPick, input } = setup()
    const file = new File(['a,b'], 'v.csv', { type: 'text/csv' })
    fireEvent.change(input, { target: { files: [file] } })
    expect(onPick).toHaveBeenCalledWith(file)
  })
})
