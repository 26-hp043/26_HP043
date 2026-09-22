// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AssistantOverlay, type AssistantOverlayProps } from './AssistantOverlay'
import { AssistantError } from './apiProvider'
import type { AssistantProvider, ChatAnswer } from './types'

/**
 * AI 어시스턴트 오버레이 (`UIFLOW 2-7` · `#121`).
 *
 * ## 무엇을 잠그나
 *
 * 생김새가 아니다 — **규격이 확정되지 않았으므로** 여기서 모양을 고정하면 확정이
 * 왔을 때 검사가 방해가 된다. 잠그는 것은 `UIFLOW 2-7`이 **이미 규정한 것**이다:
 * 오버레이로 열린다 · 라우트를 바꾸지 않는다 · 장애가 격리된다 · 면책이 붙는다.
 */

const ANSWER: ChatAnswer = {
  sessionId: 'session-1',
  answer: '현재 등급은 C입니다.',
  disclaimer: '이 답변은 화면의 계산 결과를 풀어 쓴 것입니다.',
  toolCalls: ['calc_voyage_cii'],
  discarded: false,
}

function setup(overrides: Partial<AssistantOverlayProps> = {}) {
  // 인자 타입을 명시한다 — `vi.fn(async () => …)`는 인자를 빈 튜플로 추론해
  // `mock.calls[0][0]`이 타입 검사에서 막힌다(`npm run build`에서만 드러난다).
  const ask = vi.fn<AssistantProvider['ask']>(async () => ANSWER)
  const props: AssistantOverlayProps = { provider: { ask }, ...overrides }
  render(<AssistantOverlay {...props} />)
  return { ask }
}

function open() {
  fireEvent.click(screen.getByRole('button', { name: /AI 어시스턴트 열기/ }))
}

async function send(text: string) {
  const input = screen.getByLabelText('질문')
  fireEvent.change(input, { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '보내기' }))
}

describe('열고 닫기 (`UIFLOW 2-7`)', () => {
  it('처음에는 버튼만 있다 — 화면을 가리지 않는다', () => {
    setup()
    expect(screen.getByRole('button', { name: /AI 어시스턴트 열기/ })).toBeTruthy()
    expect(screen.queryByLabelText('질문')).toBeNull()
  })

  it('버튼에서부터 **실험**임을 밝힌다', () => {
    /*
     * `PRD §20 O-12`가 MAY 수준으로 둔 기능이다. 열어 본 뒤에야 알게 하면, 답이
     * 이상할 때 사용자는 제품 전체를 의심한다.
     */
    setup()
    expect(screen.getByRole('button', { name: /실험/ })).toBeTruthy()
  })

  it('패널 안에서 Escape를 누르면 닫힌다', () => {
    /*
     * 종전 이 검사는 `window`에 Escape를 쏘아 **전역 리스너를 정답으로 들고
     * 있었다**(`#1101` ⑵). 패널 안에서 눌러 닫히는 것이 규정이고, 바깥에서
     * 눌러도 닫히지 않아야 한다 — 아래 검사가 그 반대쪽을 잠근다.
     */
    setup()
    open()
    expect(screen.getByLabelText('질문')).toBeTruthy()
    fireEvent.keyDown(screen.getByLabelText('질문'), { key: 'Escape' })
    expect(screen.queryByLabelText('질문')).toBeNull()
  })

  it('본문 다른 입력에서 Escape를 눌러도 닫히지 않는다 (`#1101` ⑵)', () => {
    /*
     * Escape는 화면 곳곳에서 쓰인다 — 조합 취소·검색어 지우기가 그렇다.
     * 전역으로 받으면 사용자가 자기 입력에서 Escape를 누른 것만으로 이 패널이
     * 사라진다.
     */
    render(
      <>
        <input aria-label="바깥 입력" />
        <AssistantOverlay provider={{ ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER) }} />
      </>,
    )
    fireEvent.click(screen.getByRole('button', { name: /AI 어시스턴트 열기/ }))
    expect(screen.getByLabelText('질문')).toBeTruthy()

    fireEvent.keyDown(screen.getByLabelText('바깥 입력'), { key: 'Escape' })

    expect(screen.getByLabelText('질문')).toBeTruthy()
  })

  it('닫으면 **여는 버튼으로 초점이 돌아온다** (WCAG 2.4.3)', () => {
    setup()
    open()
    fireEvent.click(screen.getByRole('button', { name: 'AI 어시스턴트 닫기' }))

    const launcher = screen.getByRole('button', { name: /AI 어시스턴트 열기/ })
    expect(document.activeElement).toBe(launcher)
  })

  it('닫힌 여는 버튼은 **없는 id를 가리키지 않는다**', () => {
    /*
     * 닫혀 있을 때 패널은 DOM에 없다. 그 상태의 `aria-controls`는 실재하지 않는
     * id를 가리켜, 보조기술이 따라갈 곳이 없는 참조가 된다.
     */
    setup()
    const launcher = screen.getByRole('button', { name: /AI 어시스턴트 열기/ })
    const controls = launcher.getAttribute('aria-controls')
    expect(controls === null || document.getElementById(controls) !== null).toBe(true)
  })
})

describe('한글 조합 중 Enter (`#1101` ⑴)', () => {
  it('조합 중 Enter는 보내지 않는다 — 마지막 음절이 깨진다', () => {
    const { ask } = setup()
    open()
    const input = screen.getByLabelText('질문')
    fireEvent.change(input, { target: { value: '등급이 왜 D야' } })

    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })

    expect(ask).not.toHaveBeenCalled()
  })

  it('`isComposing`을 채우지 않는 조합 경로도 막는다 — `keyCode 229`', () => {
    const { ask } = setup()
    open()
    const input = screen.getByLabelText('질문')
    fireEvent.change(input, { target: { value: '등급이 왜 D야' } })

    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 })

    expect(ask).not.toHaveBeenCalled()
  })

  it('조합이 끝난 Enter는 보낸다 — 막기만 하면 전송이 죽는다', async () => {
    const { ask } = setup()
    open()
    const input = screen.getByLabelText('질문')
    fireEvent.change(input, { target: { value: '등급이 왜 D야' } })

    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1))
    expect(ask.mock.calls[0][0].message).toBe('등급이 왜 D야')
  })

  it('Shift+Enter는 줄바꿈이다 — 보내지 않는다', () => {
    const { ask } = setup()
    open()
    const input = screen.getByLabelText('질문')
    fireEvent.change(input, { target: { value: '등급이 왜 D야' } })

    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })

    expect(ask).not.toHaveBeenCalled()
  })
})

describe('묻고 답하기', () => {
  it('답과 함께 **면책이 보인다** (`#120` 완료 기준)', async () => {
    setup()
    open()
    await send('등급 알려줘')
    await waitFor(() => expect(screen.getByText(ANSWER.answer)).toBeTruthy())
    expect(screen.getByText(ANSWER.disclaimer)).toBeTruthy()
  })

  it('두 번째 질문은 **같은 대화로** 간다', async () => {
    const { ask } = setup()
    open()
    await send('첫 질문')
    await waitFor(() => expect(screen.getByText(ANSWER.answer)).toBeTruthy())
    await send('둘째 질문')
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2))
    expect(ask.mock.calls[0][0]).toMatchObject({ sessionId: undefined })
    expect(ask.mock.calls[1][0]).toMatchObject({ sessionId: 'session-1' })
  })

  it('화면이 보고 있는 선박을 함께 보낸다', async () => {
    const { ask } = setup({ vesselId: 'vessel-9' })
    open()
    await send('등급 알려줘')
    await waitFor(() => expect(ask).toHaveBeenCalled())
    expect(ask.mock.calls[0][0]).toMatchObject({ vesselId: 'vessel-9' })
  })

  it('빈 질문은 보내지 않는다', () => {
    const { ask } = setup()
    open()
    const button = screen.getByRole('button', { name: '보내기' })
    expect((button as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(button)
    expect(ask).not.toHaveBeenCalled()
  })
})

describe('버린 답과 실패 (`PRD §16.2` 격리)', () => {
  it('폐기된 답은 **답과 다르게** 보인다 (`API_SPEC §15.2`)', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '설명되지 않는 수치가 있습니다.',
      discarded: true,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('수치 알려줘')

    const bubble = await screen.findByText(
      '답을 드리지 못했습니다 — 설명되지 않는 수치가 있습니다.',
    )
    /*
     * 규격이 정해졌다 — 2026-09-17 확정 ⓐ·ⓓ (`#1051` 3절). **채널 둘**을 잠근다.
     *
     * ⑴ 줄무늬(클래스) ⑵ 접두 문구. `§14`가 색 단독 구분을 금지하므로 ⑵가
     * 보조 채널이고, **문구는 낭독에도 실리는 유일한 채널**이라 함께 잠근다.
     *
     * 색·굵기는 여전히 고정하지 않는다 — 값은 토큰이 갖고, 여기서 잠그면
     * 토큰이 바뀔 때 화면이 아니라 검사가 먼저 깨진다.
     */
    expect(bubble.className).toContain('assistant__turn--discarded')
    expect(bubble.textContent).toContain('답을 드리지 못했습니다')

    /*
     * 면책은 **같은 신호를 쓰지 않는다**(확정 ⓓ). 종전에는 배경·줄무늬·글자색이
     * 셋 다 같아 둘을 가를 수 없었다 — 면책에 접두가 새어 들어가면 그 상태로
     * 되돌아간 것이다.
     */
    expect(screen.getByText(ANSWER.disclaimer).textContent).not.toContain(
      '답을 드리지 못했습니다',
    )
  })

  it('호출이 실패해도 **던지지 않는다** — 말풍선이 된다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => {
      throw new AssistantError('서버에 연결하지 못했습니다.')
    })
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('등급 알려줘')
    expect(await screen.findByText('서버에 연결하지 못했습니다.')).toBeTruthy()
    // 오버레이가 살아 있다 — 대시보드가 오류 화면으로 바뀌지 않는다.
    expect(screen.getByLabelText('질문')).toBeTruthy()
  })

  it('**설정이 없으면 입력을 닫는다** — 다시 눌러도 소용없다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => {
      throw new AssistantError('챗봇을 사용할 수 없습니다.', { unavailable: true })
    })
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('등급 알려줘')
    await screen.findByText('챗봇을 사용할 수 없습니다.')
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(true)
  })
})

describe('#1243 — 선박이 정해지지 않은 턴', () => {
  it('vessel_resolved=false 답은 「선박을 먼저 골라」 안내가 붙는다 (성질 단언)', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '어느 선박인지 먼저 정해야 합니다.',
      vesselResolved: false,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('CII 계산해줘')

    const bubble = await screen.findByText(/어느 선박인지/, { selector: '.assistant__turn--assistant' })
    /*
     * 문구 전문을 단언하지 않는다 (`AGENTS §4.6` — 표시 문구는 디자인이 바꿀 수
     * 있다). 잠그는 성질은 둘: ⑴ **선박을 고르라는 안내가 같은 말풍선에 있다**
     * ⑵ 폐기 접두(「답을 드리지 못했습니다」)는 아니다 — 답은 버리지 않았다.
     */
    expect(bubble.textContent).toContain('선박')
    expect(bubble.textContent).toContain('먼저')
    expect(bubble.textContent).not.toContain('답을 드리지 못했습니다')
  })

  it('vessel_resolved=true 답에는 그 안내가 없다 — 참고 답과 구분된다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      vesselResolved: true,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('등급 설명해줘')

    const bubble = await screen.findByText(ANSWER.answer, {
      selector: '.assistant__turn--assistant',
    })
    expect(bubble.textContent).not.toContain('먼저 골라')
  })
})

describe('계산 대상 · 예시 질문 · 안내 문구 (#1613 · R20)', () => {
  it('고른 선박의 이름을 패널에 보인다 — 요청에는 id만 간다 (`PRD §16.3.1`)', async () => {
    const { ask } = setup({ vesselId: 'v-1', vesselName: '샘플 벌크선' })
    open()
    const target = document.querySelector('.assistant__target') as HTMLElement
    expect(target.textContent).toContain('샘플 벌크선')
    expect(target.textContent).toContain('상단에서 바꿉니다')

    await send('연말 예상은?')
    await screen.findByText(ANSWER.answer)
    const request = ask.mock.calls[0][0]
    expect(request.vesselId).toBe('v-1')
    expect(JSON.stringify(request)).not.toContain('샘플 벌크선')
  })

  it('선박이 없으면 먼저 고르라고 말한다', () => {
    setup()
    open()
    expect(document.querySelector('.assistant__target')!.textContent).toMatch(/선택한 선박 없음/)
  })

  it('이름이 아직 없으면 id를 보이지 않는다', () => {
    setup({ vesselId: '00000000-0000-4000-8000-000000000001' })
    open()
    const target = document.querySelector('.assistant__target')!.textContent ?? ''
    expect(target).toContain('선택한 선박')
    expect(target).not.toContain('0000')
  })

  it('예시 질문을 누르면 입력칸에만 채운다 — 보내지 않는다', () => {
    const { ask } = setup({ vesselId: 'v-1', vesselName: '샘플 벌크선' })
    open()
    const examples = screen.getByRole('list', { name: '예시 질문' })
    const buttons = examples.querySelectorAll('button')
    expect(buttons).toHaveLength(3)

    // 실제 브라우저에서는 누른 버튼이 초점을 가져간다 — jsdom은 옮기지 않으므로 먼저 준다
    buttons[0].focus()
    fireEvent.click(buttons[0])
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(buttons[0].textContent)
    expect(document.activeElement).toBe(screen.getByLabelText('질문'))
    expect(ask).not.toHaveBeenCalled()
  })

  it('대화를 시작하면 예시 질문을 걷는다', async () => {
    setup()
    open()
    await send('안녕하세요')
    await screen.findByText(ANSWER.answer)
    expect(screen.queryByRole('list', { name: '예시 질문' })).toBeNull()
  })

  it('안내 문구가 「화면의 계산 결과를 풀어 설명」한다고 말하지 않는다 — 새로 계산한다(R18)', () => {
    setup()
    open()
    const intro = document.querySelector('.assistant__intro')!.textContent ?? ''
    expect(intro).not.toMatch(/화면에 나온/)
    expect(intro).toMatch(/계산해 답합니다/)
  })
})

describe('열림을 셸에 알린다 (#1613 · R21)', () => {
  it('열고 닫을 때 onOpenChange가 불린다', () => {
    const onOpenChange = vi.fn()
    setup({ onOpenChange })
    expect(onOpenChange).toHaveBeenLastCalledWith(false)
    open()
    expect(onOpenChange).toHaveBeenLastCalledWith(true)
    fireEvent.click(screen.getByRole('button', { name: 'AI 어시스턴트 닫기' }))
    expect(onOpenChange).toHaveBeenLastCalledWith(false)
  })
})

describe('패널을 열 때 사용 가능 여부를 먼저 묻는다 (`#1535` · `API_SPEC §15.7`)', () => {
  it('서버가 「쓸 수 없음」이면 질문하기 전에 안내하고 입력을 닫는다', async () => {
    const status = vi.fn(async () => ({ available: false }))
    const { ask } = setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(screen.getByRole('status').textContent).not.toBe(''))
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(true)
    expect(status).toHaveBeenCalledTimes(1)
    expect(ask).not.toHaveBeenCalled()
  })

  it('「쓸 수 있음」이면 안내 없이 질문을 받는다', async () => {
    const status = vi.fn(async () => ({ available: true }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(status).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('조회가 실패하면 입력을 막지 않는다 — 모르는 상태를 「쓸 수 없음」으로 그리지 않는다', async () => {
    const status = vi.fn(async () => {
      throw new AssistantError('상태를 확인하지 못했습니다 (HTTP 500).')
    })
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(status).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(false)
  })
})
