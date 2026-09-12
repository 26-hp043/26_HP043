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

  it('Escape로 닫힌다', () => {
    setup()
    open()
    expect(screen.getByLabelText('질문')).toBeTruthy()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByLabelText('질문')).toBeNull()
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

    const bubble = await screen.findByText('설명되지 않는 수치가 있습니다.')
    /*
     * 같은 모양으로 두면 사용자는 「답을 받았다」고 읽는다. 받은 것은 답이 아니라
     * 「답을 못 드린 이유」다. 클래스로 잠그는 것이 규격 확정 전에 할 수 있는
     * 가장 약한 단언이다 — 색·굵기를 고정하면 확정이 왔을 때 방해가 된다.
     */
    expect(bubble.className).toContain('assistant__turn--discarded')
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
