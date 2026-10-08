// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssistantOverlay, type AssistantOverlayProps } from './AssistantOverlay'
import { AssistantError } from './apiProvider'
import type { AssistantProvider, ChatAnswer } from './types'
import { publishScreenResult, resetScreenResult } from './screenResult'

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
  disclaimer: '이 답변은 BlueLog의 계산 결과와 규제 기준값 표를 풀어 쓴 것입니다.',
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

/**
 * 근거 칩 (#1818 · `API_SPEC §15.1`).
 *
 * `tool_calls`는 **그 답의 값을 무엇이 냈는지**다. `§20 O-12` No-Compute가 「값을
 * 지어내지 않고 계산이 낸 값을 인용한다」이므로, 무엇이 냈는지가 보이는 쪽이 그
 * 조항에 맞다. 서버가 보내고 provider가 파싱해 두었는데 화면이 읽지 않고 있었다.
 */
describe('근거 (#1818)', () => {
  it('답 아래에 값을 낸 도구를 **한국어로** 적는다', async () => {
    setup()
    open()
    await send('이 항차 CII 알려줘')

    // ANSWER.toolCalls = ['calc_voyage_cii']
    const cite = await screen.findByText(/항차 CII 계산/)
    expect(cite.textContent).toContain('근거')
    // 도구 이름이 날것으로 새지 않는다.
    expect(document.body.textContent).not.toContain('calc_voyage_cii')
  })

  it('⚠️ **버린 답에는 붙이지 않는다** — 답이 아닌 것에 근거를 달면 답으로 읽힌다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '설명되지 않는 수치가 있습니다.',
      discarded: true,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('수치 알려줘')

    await screen.findByText(/^답을 드리지 못했습니다/)
    expect(screen.queryByText(/항차 CII 계산/)).toBeNull()
  })

  it('호출이 실패한 말풍선에도 붙지 않는다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => {
      throw new AssistantError('챗봇을 사용할 수 없습니다.')
    })
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('알려줘')

    await screen.findByText('챗봇을 사용할 수 없습니다.')
    expect(screen.queryByText(/근거/)).toBeNull()
  })

  it('도구를 부르지 않은 답에는 빈 칩을 그리지 않는다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({ ...ANSWER, toolCalls: [] }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('attained CII가 뭔가요?')

    await screen.findByText(ANSWER.answer)
    expect(screen.queryByText(/근거/)).toBeNull()
  })
})

/**
 * 첫 화면의 말은 첫 화면에 (#1818).
 *
 * 안내문은 「무엇을 물어볼 수 있나」를 말하는 문장이라 아직 물어본 것이 없을 때가 그
 * 말이 쓰일 때다. 예시 질문이 이미 그 규칙이고(`#1613`), 안내문만 남아 대화 내내
 * 50px을 쓰고 있었다.
 */
describe('안내문과 빈 로그 (#1818)', () => {
  it('열자마자는 안내문과 빈 로그 한 줄이 보인다', () => {
    setup()
    open()
    expect(screen.getByText(/규제 판단이나 권고는 하지 않으며/)).toBeTruthy()
    expect(screen.getByText(/답과 그 근거가 여기에 쌓입니다/)).toBeTruthy()
  })

  it('대화가 시작되면 둘 다 걷힌다 — 그 자리는 로그가 쓴다', async () => {
    setup()
    open()
    await send('올해 연말 예상 등급은?')

    await screen.findByText(ANSWER.answer)
    expect(screen.queryByText(/규제 판단이나 권고는 하지 않으며/)).toBeNull()
    expect(screen.queryByText(/답과 그 근거가 여기에 쌓입니다/)).toBeNull()
  })
})

/**
 * 범이 런처와 소개 일러스트 (#2008).
 *
 * ## 무엇을 잠그나
 *
 * 그림이 예쁜지가 아니다. **이름이 그림으로 바뀌면서 사라지지 않았는가**와
 * **장식이 접근성 트리에 끼어들지 않는가**를 본다. 둘 다 눈으로는 드러나지 않는다 —
 * 화면은 똑같이 잘 보이고, 스크린리더에서만 버튼이 이름 없는 버튼이 된다.
 *
 * 크기는 여기서 보지 않는다. `§16 항목 16`이 조건부 대기라 값은 CSS가 갖고,
 * jsdom은 어차피 레이아웃을 계산하지 않는다 — `launcherReserve.sync.test.ts`가
 * 소스에서 「예약 폭이 런처 지름을 따라가는가」를 본다.
 */
describe('범이 런처와 소개 일러스트 (#2008)', () => {
  function launcher() {
    return screen.getByRole('button', { name: /AI 어시스턴트 열기/ })
  }

  it('런처가 범이 얼굴 그림이고, 버튼 이름은 글자로 남는다', () => {
    /*
     * 라벨이 `<img>`로 바뀌었으므로 이름은 `aria-label`이 든다. 이것이 빠지면
     * 버튼이 **이름 없는 버튼**이 되고, 위 검사들이 쓰는 `/AI 어시스턴트 열기/`
     * 조회가 전부 무너진다 — 그때는 이 검사가 먼저 말한다.
     */
    setup()
    const img = launcher().querySelector('img')
    expect(img, '런처 안에 그림이 없습니다').not.toBeNull()
    expect(img!.getAttribute('src')).toMatch(/beomi-3d-default-56/)
  })

  it('런처 그림은 장식이다 — 이름을 두 번 읽지 않는다', () => {
    setup()
    expect(launcher().querySelector('img')!.getAttribute('alt')).toBe('')
    // 그림이 이름을 거들면 「AI 어시스턴트 열기 (실험) 범이」처럼 두 번 읽힌다.
    expect(launcher().textContent).toBe('')
  })

  it('런처 그림이 화면 배율을 따라간다 — `@1x`/`@2x` 둘 다 건다', () => {
    /*
     * `srcSet`이 없으면 고배율 화면에서 56px 원본이 늘어나 뭉갠다. 눈으로는
     * 「좀 흐리네」로만 보여 회귀가 조용하다.
     */
    setup()
    const srcset = launcher().querySelector('img')!.getAttribute('srcset') ?? ''
    expect(srcset).toMatch(/beomi-3d-default-56@1x\.webp 1x/)
    expect(srcset).toMatch(/beomi-3d-default-56@2x\.webp 2x/)
  })

  it('대화가 없으면 소개 일러스트를 그린다', () => {
    setup()
    open()
    const art = document.querySelector('.assistant__intro-art')
    expect(art, '소개 일러스트가 없습니다').not.toBeNull()
    expect(art!.getAttribute('src')).toMatch(/beomi-3d-intro-160/)
  })

  it('첫 메시지를 보내면 소개 일러스트가 걷힌다', async () => {
    setup()
    open()
    await send('올해 연말 예상 등급은?')

    await screen.findByText(ANSWER.answer)
    expect(document.querySelector('.assistant__intro-art')).toBeNull()
  })

  it('소개 일러스트는 장식이다 — 안내문이 뜻을 갖는다 (`§14`)', () => {
    /*
     * `§14`는 그림 단독으로 뜻을 전하는 것을 금한다. 여기서 뜻을 지는 것은
     * `.assistant__intro` 문장과 예시 질문이고, 그림은 거들지 않는다.
     */
    setup()
    open()
    const art = document.querySelector('.assistant__intro-art')!
    expect(art.getAttribute('alt')).toBe('')
    expect(art.getAttribute('aria-hidden')).toBe('true')
    expect(screen.getByText(/규제 판단이나 권고는 하지 않으며/)).toBeTruthy()
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

    /*
     * #1818 — 접두가 **자기 요소**(`<strong>`)가 되어 텍스트가 갈린다. 말풍선을
     * 문장 전체로 찾지 않고, 접두를 품은 말풍선으로 찾는다.
     */
    const prefix = await screen.findByText(/^답을 드리지 못했습니다/)
    const bubble = prefix.closest('p')!
    /*
     * 규격이 정해졌다 — 2026-09-17 확정 ⓐ·ⓓ (`#1051` 3절). **채널 둘**을 잠근다.
     *
     * ⑴ 줄무늬(클래스) ⑵ 접두 문구. `§14`가 색 단독 구분을 금지하므로 ⑵가
     * 보조 채널이고, **문구는 낭독에도 실리는 유일한 채널**이라 함께 잠근다.
     *
     * **색은 여전히 고정하지 않는다** — `§8.5`가 색 이름을 Figma에 맡겼다. #1818이
     * 더한 굵기도 값이 아니라 **자리**로 잠근다(접두가 자기 요소를 갖는가). 값을
     * 여기서 잠그면 토큰이 바뀔 때 화면이 아니라 검사가 먼저 깨진다.
     */
    expect(bubble.className).toContain('assistant__turn--discarded')
    expect(bubble.textContent).toContain('답을 드리지 못했습니다')
    expect(bubble.textContent).toContain('설명되지 않는 수치가 있습니다.')
    expect(prefix.tagName).toBe('STRONG')
    expect(prefix.className).toContain('assistant__prefix')

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

  it('선박 없이 도는 도구(lookup_regulation)만으로 답했으면 안내를 붙이지 않는다 (#1535)', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '벌크선의 등급 경계는 비율로 정해집니다.',
      toolCalls: ['lookup_regulation'],
      vesselResolved: false,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('벌크선 등급 기준 알려줘')

    const bubble = await screen.findByText(/등급 경계는 비율로/, { selector: '.assistant__turn--assistant' })
    expect(bubble.textContent).not.toContain('먼저 골라')
  })

  it('화면 결과 설명(explain_screen_result)만으로 답했으면 안내를 붙이지 않는다 (#1991)', async () => {
    /*
     * 계산한 뒤 상단 셀렉트를 「선박 선택 안 함」으로 되돌리면 결과는 그 주소에 남고
     * 상단 선박만 없다. 서버는 그때 실행의 선박을 따지지 않고 저장된 결과를 읽어 정상
     * 답을 낸다 — 그 답에 「선박을 먼저 골라 주세요」가 붙으면 **틀린 말**이 된다.
     */
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '이 화면의 계산 결과는 연말 예상 등급이 C입니다.',
      toolCalls: ['explain_screen_result'],
      vesselResolved: false,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('이 결과 설명해줘')

    const bubble = await screen.findByText(/연말 예상 등급이 C/, { selector: '.assistant__turn--assistant' })
    expect(bubble.textContent).not.toContain('먼저 골라')
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
    // 10/7 결정(#2322) — 계산 대상 줄은 머리 줄 안에 있다.
    expect(target.closest('header')).not.toBeNull()
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
    const examples = screen.getByRole('group', { name: '예시 질문' })
    /*
     * 10/7 결정(#2322)으로 예시는 문의 유형별 접기(`<details>`)로 묶였다 — 종전의 「셋」은 개수가
     * 아니라 「도구가 답할 수 있는 것만」의 대리 지표였으므로, 여기서는 묶음의 성질을 본다:
     * 묶음이 여럿이고, 첫 묶음만 펼쳐져 있고, 묶음마다 고를 질문이 있다.
     */
    const groups = [...examples.querySelectorAll('details')]
    expect(groups.length).toBeGreaterThan(1)
    expect(groups.map((group) => group.open)).toEqual(groups.map((_, index) => index === 0))
    for (const group of groups) {
      expect(group.querySelector('summary')?.textContent?.trim()).not.toBe('')
      expect(group.querySelectorAll('button').length).toBeGreaterThan(0)
    }
    const buttons = examples.querySelectorAll('button')

    // 버튼의 화살표(`aria-hidden`)는 질문이 아니다 — 입력칸에 들어가는 것은 질문 글자뿐이다.
    const question = (button: Element) => {
      const copy = button.cloneNode(true) as Element
      copy.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove())
      return copy.textContent?.trim() ?? ''
    }

    // 실제 브라우저에서는 누른 버튼이 초점을 가져간다 — jsdom은 옮기지 않으므로 먼저 준다
    buttons[0].focus()
    fireEvent.click(buttons[0])
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(question(buttons[0]))
    expect(document.activeElement).toBe(screen.getByLabelText('질문'))
    expect(ask).not.toHaveBeenCalled()
  })

  it('대화를 시작하면 첫 화면의 예시를 걷고, 답 뒤에 「이어서 물어보기」 접힘으로 다시 둔다 (#2344)', async () => {
    setup()
    open()
    await send('안녕하세요')
    await screen.findByText(ANSWER.answer)
    // 첫 화면의 펼친 예시(머리말 포함)는 걷힌다 — 대화가 자리를 쓴다
    expect(screen.queryByText('무엇이 궁금하세요?')).toBeNull()

    // 대신 한 줄 접힘이 있고, 펼치면 문의 유형 묶음이 전부 접힌 채 있다
    const followup = document.querySelector('details.assistant__followup') as HTMLDetailsElement
    expect(followup).not.toBeNull()
    expect(followup.open).toBe(false)
    const groups = within(followup).getByRole('group', { name: '예시 질문' })
    const details = Array.from(groups.querySelectorAll('details'))
    expect(details.length).toBeGreaterThan(1)
    expect(details.every((d) => !d.open)).toBe(true)

    // 답이 올 때마다 예시까지 낭독되지 않게 — 로그(`role="log"`) 밖에 있다
    expect(followup.closest('[role="log"]')).toBeNull()

    // 누르면 처음과 같이 입력칸에만 채운다 (화살표는 `aria-hidden`이라 질문 글자가 아니다)
    const example = within(groups).getAllByRole('button', { hidden: true })[0]
    const question = (button: Element) => {
      const copy = button.cloneNode(true) as Element
      copy.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove())
      return copy.textContent?.trim() ?? ''
    }
    fireEvent.click(example)
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(question(example))
  })

  it('안내 문구가 「화면의 계산 결과를 풀어 설명」한다고 말하지 않는다 — 새로 계산한다(R18)', () => {
    setup()
    open()
    /*
     * 10/7 결정(#2322)으로 안내는 짧은 한 줄 + 「범이가 하는 일」 접기로 나뉘었다. 긴 설명은 접기
     * 안에 그대로 있으므로 **안내 전체**(한 줄 + 접기)를 읽는다.
     */
    const intro = document.querySelector('.assistant__intro-wrap')!.textContent ?? ''
    expect(document.querySelector('.assistant__intro-wrap details summary')).not.toBeNull()
    expect(intro).not.toMatch(/화면에 나온/)
    expect(intro).toMatch(/계산해 답합니다/)
  })

  it('안내 문구와 면책이 **같은 출처**를 말한다 (#1993)', () => {
    /*
     * 면책(`PRD §6.3` 정본 · `#1986`)은 출처를 **둘**로 말한다 — 「BlueLog의 계산 결과와
     * 규제 기준값 표」. 안내문은 「수치는 **계산 엔진이 낸 값만** 인용합니다」로 앞의 것만
     * 말해, 같은 패널의 위와 아래가 어긋났다.
     *
     * 문구 전문을 단언하지 않는다(표시 문구 · `AGENTS §4.6`) — **면책이 부르는 두 출처가
     * 안내문에도 있는가**를 본다. 면책이 바뀌면 이 검사가 그쪽을 따라간다.
     */
    setup()
    open()
    const intro = document.querySelector('.assistant__intro')!.textContent ?? ''
    expect(ANSWER.disclaimer).toContain('계산 결과')
    expect(ANSWER.disclaimer).toContain('규제 기준값')
    expect(intro).toMatch(/계산/)
    expect(intro).toMatch(/규제 기준값/)
    // 「…만 인용합니다」로 출처를 하나로 좁히지 않는다.
    expect(intro).not.toMatch(/계산 엔진이 낸 값만/)
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
      throw new AssistantError('상태를 확인하지 못했습니다.')
    })
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(status).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(false)
  })
})

describe('둘러보기 세션에서는 막는다 (#2110 · `UIFLOW 2-7`)', () => {
  /*
   * 문구는 표시 문구라(`AGENTS §4.6`) 리터럴로 단언하지 않는다. 지키려는 성질은 셋이다 —
   * 질문하기 전에 안내가 뜬다 · 입력과 예시가 닫힌다 · 그 안내가 「설정이 없어 쓸 수 없음」과
   * **다른 말**이다(둘러보기에 「관리자에게 문의」는 할 수 있는 일이 아니다).
   */
  it('열자마자 안내를 내고 입력 · 예시를 닫는다 — 상태를 묻지도, 질문을 보내지도 않는다', async () => {
    const status = vi.fn(async () => ({ available: true }))
    const { ask } = setup({
      provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status },
      tour: true,
    })
    open()
    expect(screen.getByRole('status').textContent).not.toBe('')
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(true)
    const examples = screen.getAllByRole('button').filter((b) => b.className === 'assistant__example')
    expect(examples.length).toBeGreaterThan(0)
    for (const example of examples) expect((example as HTMLButtonElement).disabled).toBe(true)
    expect(status).not.toHaveBeenCalled()
    expect(ask).not.toHaveBeenCalled()
  })

  it('둘러보기 안내는 「쓸 수 없음」(#1535) 안내와 다른 말이다', async () => {
    const tourView = render(
      <AssistantOverlay provider={{ ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER) }} tour />,
    )
    open()
    const tourText = screen.getByRole('status').textContent
    tourView.unmount()

    const status = vi.fn(async () => ({ available: false }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(screen.getByRole('status').textContent).not.toBe(''))
    expect(screen.getByRole('status').textContent).not.toBe(tourText)
  })

  it('세션 확인이 늦어 첫 렌더 뒤에 둘러보기가 되어도 입력을 닫는다', () => {
    const provider = { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER) }
    const view = render(<AssistantOverlay provider={provider} />)
    open()
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(false)
    view.rerender(<AssistantOverlay provider={provider} tour />)
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).disabled).toBe(true)
    expect(screen.getByRole('status').textContent).not.toBe('')
  })
})

describe('화면의 결과를 함께 보낸다 (`#1533`)', () => {
  it('지금 화면이 낸 결과의 실행 id를 질문에 싣는다', async () => {
    publishScreenResult('run-7')
    try {
      const { ask } = setup()
      open()
      await send('이 결과가 왜 D인가요?')
      await waitFor(() => expect(ask).toHaveBeenCalled())
      expect(ask.mock.calls[0][0].calculationRunId).toBe('run-7')
    } finally {
      resetScreenResult()
    }
  })

  it('결과를 낸 적이 없으면 싣지 않는다', async () => {
    resetScreenResult()
    const { ask } = setup()
    open()
    await send('안녕하세요')
    await waitFor(() => expect(ask).toHaveBeenCalled())
    expect(ask.mock.calls[0][0].calculationRunId).toBeUndefined()
  })
})

/**
 * 머리·말풍선 아바타의 표정 (#2009).
 *
 * ## 무엇을 잠그나
 *
 * 표정 **표의 네 행이 화면에 닿는가**다. `avatarMood.test.ts`가 순수 함수로 네 행을
 * 보고, 여기서는 그 값이 실제로 `<img>`까지 가는지와 **장식으로 남는지**를 본다 —
 * 함수만 맞고 화면이 안 읽으면 아무것도 바뀌지 않으며, 그 실패는 눈으로 드러나지
 * 않는다(얼굴은 늘 하나 떠 있다).
 *
 * 크기는 보지 않는다 — `§16 항목 16`이 조건부 대기라 값은 CSS가 갖는다.
 */
describe('머리·말풍선 아바타의 표정 (#2009)', () => {
  const head = () => document.querySelector('.assistant__head-avatar') as HTMLImageElement
  const bubbleAvatars = () =>
    [...document.querySelectorAll('.assistant__avatar')] as HTMLImageElement[]

  it('대기 — 머리는 `default` 얼굴이다', () => {
    setup()
    open()
    expect(head().getAttribute('src')).toMatch(/beomi-3d-default-40/)
  })

  it('답을 받으면 머리가 `default` → `guide`로 바뀐다', async () => {
    setup()
    open()
    expect(head().getAttribute('src')).toMatch(/default/)

    await send('올해 연말 예상 등급은?')
    await screen.findByText(ANSWER.answer)

    expect(head().getAttribute('src')).toMatch(/beomi-3d-guide-40/)
  })

  it('실패하면 머리가 `warning`으로 바뀐다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => {
      throw new AssistantError('서버에 연결하지 못했습니다.')
    })
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('알려줘')
    await screen.findByText('서버에 연결하지 못했습니다.')

    expect(head().getAttribute('src')).toMatch(/beomi-3d-warning-40/)
  })

  it('⚠️ 보내는 중에는 머리 아바타가 바뀌지 않는다', async () => {
    /*
     * 이것이 **의도**다 (`#2009` 표의 「답변 작성 중」 행). 쓸 수 있는 얼굴이
     * `default`와 같아 바꿔도 화면에서 보이지 않으므로, 바꾸는 시늉을 하지 않는다.
     * 작성 중은 `PENDING_TEXT`가 말한다 — 그 줄이 함께 떠 있는 것도 본다.
     */
    let release: ((answer: ChatAnswer) => void) | undefined
    const ask = vi.fn<AssistantProvider['ask']>(
      () =>
        new Promise<ChatAnswer>((resolve) => {
          release = resolve
        }),
    )
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    const before = head().getAttribute('src')

    await send('올해 연말 예상 등급은?')
    await waitFor(() => expect(ask).toHaveBeenCalled())

    expect(document.querySelector('.assistant__turn--pending')).not.toBeNull()
    expect(head().getAttribute('src')).toBe(before)

    release!(ANSWER)
    await screen.findByText(ANSWER.answer)
    expect(head().getAttribute('src')).toMatch(/guide/)
  })

  it('⚠️ 열자마자 「쓸 수 없음」이면 턴이 없어도 머리가 `warning`이다', async () => {
    /*
     * `statusOff`(#1535)는 **턴과 무관한** 상태라, 배선이 빠지면 대기와 똑같이
     * `default` 얼굴이 뜬다 — 안내문은 떠 있는데 얼굴만 멀쩡한 꼴이다. 턴이 하나도
     * 없는 자리를 골랐으므로 이 검사는 `statusOff`가 실제로 전해지는지만 본다
     * (턴이 있으면 그 턴의 `failed`만으로도 `warning`이 되어 아무것도 못 가른다).
     */
    const status = vi.fn(async () => ({ available: false }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(status).toHaveBeenCalled())

    expect(document.querySelectorAll('.assistant__turn').length).toBe(0)
    await waitFor(() => expect(head().getAttribute('src')).toMatch(/beomi-3d-warning-40/))
  })

  it('말풍선 아바타는 **어시스턴트 턴에만** 붙는다 — 사용자 턴에는 없다', async () => {
    setup()
    open()
    await send('올해 연말 예상 등급은?')
    await screen.findByText(ANSWER.answer)

    // 턴은 둘(사용자 · 어시스턴트)인데 아바타는 하나다.
    expect(document.querySelectorAll('.assistant__turn').length).toBe(2)
    expect(bubbleAvatars().length).toBe(1)
    expect(bubbleAvatars()[0].getAttribute('src')).toMatch(/beomi-2d-guide\.svg/)
  })

  it('말풍선 아바타는 3D가 아니라 2D다 — 32px 이하에서 3D는 뭉개진다', async () => {
    setup()
    open()
    await send('등급?')
    await screen.findByText(ANSWER.answer)

    const src = bubbleAvatars()[0].getAttribute('src') ?? ''
    expect(src).toMatch(/beomi-2d-/)
    expect(src).not.toMatch(/beomi-3d-/)
  })

  it('폐기된 답의 말풍선에는 경고 표정이 붙는다 — §8.5의 두 채널은 그대로다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '설명되지 않는 수치가 있습니다.',
      discarded: true,
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('수치 알려줘')
    const prefix = await screen.findByText(/^답을 드리지 못했습니다/)

    expect(bubbleAvatars()[0].getAttribute('src')).toMatch(/beomi-2d-warning\.svg/)
    // 아바타를 더했다고 기존 두 채널이 대체되지 않는다 (`§8.5` 🔒).
    expect(prefix.closest('p')!.className).toContain('assistant__turn--discarded')
  })

  it('실패한 턴에는 경고 표정 아바타가 붙는다', async () => {
    const ask = vi.fn<AssistantProvider['ask']>(async () => {
      throw new AssistantError('서버에 연결하지 못했습니다.')
    })
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('알려줘')
    await screen.findByText('서버에 연결하지 못했습니다.')

    expect(bubbleAvatars()[0].getAttribute('src')).toMatch(/beomi-2d-warning\.svg/)
  })

  it('면책에는 아바타를 붙이지 않는다', async () => {
    setup()
    open()
    await send('등급?')
    await screen.findByText(ANSWER.answer)

    const disclaimer = document.querySelector('.assistant__disclaimer')!
    expect(disclaimer.querySelector('img')).toBeNull()
    // 면책은 로그 밖이라 말풍선 줄에도 들어가지 않는다.
    expect(disclaimer.closest('.assistant__turn-row')).toBeNull()
  })

  it('아바타는 전부 장식이다 — 낭독에 끼어들지 않는다 (`§14`)', async () => {
    setup()
    open()
    await send('등급?')
    await screen.findByText(ANSWER.answer)

    for (const img of [head(), ...bubbleAvatars()]) {
      expect(img.getAttribute('alt')).toBe('')
      expect(img.getAttribute('aria-hidden')).toBe('true')
    }
    /*
     * 상태의 뜻은 기존 채널이 진다 — 아바타를 `§8.5`의 구분 채널로 쓰지 않는다.
     * 폐기와 실패가 같은 `warning` 얼굴이어도 두 채널은 그대로다.
     */
    expect(screen.getByText(ANSWER.disclaimer)).toBeTruthy()
  })
})

describe('마크다운 기호 (`#2064`)', () => {
  it('어시스턴트 답에서는 걷고, 사용자가 친 글자는 그대로 둔다', async () => {
    /*
     * 사용자가 별표를 쳤다면 그것은 서식이 아니라 **그가 친 글자**다. 말풍선 하나를
     * 두 역할이 함께 쓰므로, 걷는 일을 역할로 가르지 않으면 사용자 글자까지 바뀐다.
     */
    const ask = vi.fn<AssistantProvider['ask']>(async () => ({
      ...ANSWER,
      answer: '기준 CII의 **1.0600배** 초과입니다',
    }))
    render(<AssistantOverlay provider={{ ask }} />)
    open()
    await send('**이것은 내가 친 별표다**')

    await waitFor(() => {
      expect(screen.getByText('기준 CII의 1.0600배 초과입니다')).toBeTruthy()
    })
    expect(screen.getByText('**이것은 내가 친 별표다**')).toBeTruthy()
  })
})

describe('범이 첫 방문 안내 (#2205)', () => {
  const HINT = /CII가 처음이라면 범이에게 물어보세요/

  function reset() {
    window.localStorage.clear()
    window.sessionStorage.clear()
  }

  it('처음 들어오면 런처 위에 말풍선이 뜨고, 초점을 가져가지 않는다', () => {
    reset()
    setup()
    const hint = screen.getByRole('status')
    expect(hint.textContent).toMatch(HINT)
    expect(screen.getByRole('button', { name: /AI 어시스턴트 열기/ })).toBeTruthy()
    expect(document.activeElement).toBe(document.body)
  })

  it('운항 행동을 제안하지 않는다 — 기능만 안내한다 (UIFLOW 2-7 No-Advice)', () => {
    reset()
    setup()
    expect(screen.getByRole('status').textContent).not.toMatch(/하세요|낮추|감속|최적|추천/)
  })

  it('「다시 보지 않기」를 누르면 사라지고, 다시 그려도 뜨지 않는다', () => {
    reset()
    const { unmount } = render(<AssistantOverlay provider={{ ask: vi.fn() }} />)
    fireEvent.click(screen.getByRole('button', { name: '다시 보지 않기' }))
    expect(screen.queryByText(HINT)).toBeNull()
    unmount()
    window.sessionStorage.clear()
    render(<AssistantOverlay provider={{ ask: vi.fn() }} />)
    expect(screen.queryByText(HINT)).toBeNull()
  })

  it('「닫기」는 이 탭에서만 — 새 탭(탭 저장소가 빈 상태)에서는 다시 뜬다', () => {
    reset()
    const { unmount } = render(<AssistantOverlay provider={{ ask: vi.fn() }} />)
    fireEvent.click(screen.getByRole('button', { name: '닫기' }))
    expect(screen.queryByText(HINT)).toBeNull()
    unmount()
    const again = render(<AssistantOverlay provider={{ ask: vi.fn() }} />)
    expect(screen.queryByText(HINT)).toBeNull()
    again.unmount()
    window.sessionStorage.clear()
    render(<AssistantOverlay provider={{ ask: vi.fn() }} />)
    expect(screen.getByText(HINT)).toBeTruthy()
  })

  it('패널을 한 번 열면 안내를 다시 띄우지 않는다', () => {
    reset()
    setup()
    open()
    fireEvent.click(screen.getByRole('button', { name: 'AI 어시스턴트 닫기' }))
    expect(screen.queryByText(HINT)).toBeNull()
    expect(window.localStorage.getItem('bluelog.assistant.introHintDismissed')).toBe('true')
  })

  it('말풍선이 떠 있어도 화면의 Tab 순서는 그대로고, 늘어난 정지점은 런처 바로 앞의 둘뿐이다 (#2297)', async () => {
    // 화면 쪽 정지점 둘을 앞에 두고, 말풍선이 있을 때와 없을 때의 Tab 순서를 견준다.
    async function tabOrder(): Promise<string[]> {
      const user = userEvent.setup()
      const stops: string[] = []
      for (let i = 0; i < 6; i += 1) {
        await user.tab()
        const active = document.activeElement as HTMLElement
        if (active === document.body) break
        const name = active.getAttribute('aria-label') ?? active.textContent ?? ''
        if (stops.includes(name)) break
        stops.push(name)
      }
      return stops
    }
    function mount() {
      return render(
        <>
          <button type="button">화면 앞</button>
          <button type="button">화면 뒤</button>
          <AssistantOverlay provider={{ ask: vi.fn() }} />
        </>,
      )
    }

    reset()
    const withHint = mount()
    expect(screen.queryByRole('status')).not.toBeNull()
    const hinted = await tabOrder()
    withHint.unmount()

    // 안내를 이미 본 사람 — 말풍선이 없다
    window.localStorage.setItem('bluelog.assistant.introHintDismissed', 'true')
    const plain = mount()
    expect(screen.queryByRole('status')).toBeNull()
    const bare = await tabOrder()
    plain.unmount()

    // 화면 쪽 순서는 같고, 런처는 여전히 마지막이다
    expect(hinted.slice(0, 2)).toEqual(bare.slice(0, 2))
    expect(hinted[hinted.length - 1]).toBe(bare[bare.length - 1])
    // 늘어난 정지점은 말풍선의 버튼 둘뿐이고 화면 쪽과 런처 사이에 놓인다
    expect(hinted).toHaveLength(bare.length + 2)
    expect(hinted.slice(2, 4)).toHaveLength(2)
    expect(hinted.slice(2, 4)).not.toContain(bare[bare.length - 1])
  })
})

/*
 * 쓸 수 없는 상태에서도 **초점이 패널 안에 있다** (#2128 ⑷).
 *
 * 여는 순간 초점은 입력으로 간다. 그런데 「쓸 수 없음」이면 입력이 `disabled`라 초점을
 * 받지 못하고(이미 받았다면 잃고) `body`에 남는다. Escape는 **패널 안에서만** 받으므로
 * (`#1101`) 키보드로 연 사람이 키보드로 닫을 수 없었다.
 */
describe('쓸 수 없는 상태의 초점 (#2128)', () => {
  const inputClosed = () => (screen.getByLabelText('질문') as HTMLTextAreaElement).disabled
  const focusIsUsable = () => {
    const active = document.activeElement as HTMLElement
    expect(active.closest('.assistant')).not.toBeNull()
    expect(active.matches(':disabled')).toBe(false)
  }

  it('키보드로 열고 Escape로 닫을 수 있다 — 닫으면 여는 버튼으로 돌아간다', async () => {
    const status = vi.fn(async () => ({ available: false }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(inputClosed()).toBe(true))

    focusIsUsable()
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })

    const launcher = screen.getByRole('button', { name: /AI 어시스턴트 열기/ })
    expect(document.activeElement).toBe(launcher)
  })

  it('다시 열 때 — 입력이 처음부터 닫혀 있어도 초점이 패널 안에 놓인다', async () => {
    const status = vi.fn(async () => ({ available: false }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(inputClosed()).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'AI 어시스턴트 닫기' }))

    open()
    // 상태 조회가 돌아오기 **전**이다 — 입력은 지난번에 닫힌 그대로다.
    expect(inputClosed()).toBe(true)
    focusIsUsable()
    await waitFor(() => expect(status).toHaveBeenCalledTimes(2))
    focusIsUsable()
  })

  it('쓸 수 있으면 종전대로 입력이 초점을 받는다', async () => {
    const status = vi.fn(async () => ({ available: true }))
    setup({ provider: { ask: vi.fn<AssistantProvider['ask']>(async () => ANSWER), status } })
    open()
    await waitFor(() => expect(status).toHaveBeenCalled())
    expect(document.activeElement).toBe(screen.getByLabelText('질문'))
  })
})
