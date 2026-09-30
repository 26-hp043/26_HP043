/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { avatarMood, turnMood } from './avatarMood'
import type { ChatTurn } from './types'

/**
 * 아바타 표정 (`#2009`).
 *
 * 표의 네 행을 그대로 잠근다 — 대기 · 정상 답변 · 폐기 · 실패/사용 불가.
 * 「작성 중」 행은 **아바타가 바뀌지 않는다**가 규정이라 이 함수에 인자가 없고,
 * 화면에서 실제로 바뀌지 않는지는 `AssistantOverlay.test.tsx`가 본다.
 */
const IDLE = { stopped: false }

function turn(over: Partial<ChatTurn> = {}): ChatTurn {
  return { id: '1', role: 'assistant', text: '현재 등급은 C입니다.', ...over }
}

describe('아바타 표정 (#2009)', () => {
  it('대기 — 어시스턴트 턴이 없으면 `default`', () => {
    expect(avatarMood([], IDLE)).toBe('default')
    expect(avatarMood([turn({ role: 'user', text: '등급?' })], IDLE)).toBe('default')
  })

  it('정상 답변 — `guide`', () => {
    expect(avatarMood([turn()], IDLE)).toBe('guide')
  })

  it('서버가 답을 폐기 — `warning`', () => {
    expect(avatarMood([turn({ discarded: true })], IDLE)).toBe('warning')
  })

  it('호출 실패 · 사용 불가 — `warning`', () => {
    expect(avatarMood([turn({ failed: true })], IDLE)).toBe('warning')
    expect(avatarMood([], { stopped: true })).toBe('warning')
  })

  it('머리는 **마지막** 어시스턴트 턴을 따른다 — 사용자 턴이 뒤에 와도', () => {
    const turns = [
      turn({ id: '1', discarded: true }),
      turn({ id: '2' }),
      turn({ id: '3', role: 'user', text: '그럼 속도를 줄이면?' }),
    ]
    expect(avatarMood(turns, IDLE)).toBe('guide')
  })

  it('⚠️ 「쓸 수 없음」이 마지막 턴보다 앞선다', () => {
    /*
     * 답을 하나 받은 뒤에 설정이 꺼지면(`statusOff`) 머리가 `guide`로 남아
     * 「멀쩡하다」고 말하게 된다. 입력칸은 이미 닫혀 있는데 얼굴만 웃는 꼴이다.
     */
    expect(avatarMood([turn()], { stopped: true })).toBe('warning')
  })

  it('폐기와 실패는 **같은 얼굴**이다 — 가르는 것은 §8.5의 두 채널이다', () => {
    /*
     * `DESIGN_SYSTEM §8.5`는 접두 문구와 줄무늬로 둘을 가른다. 아바타는 장식이라
     * 구분 채널이 아니므로 같은 얼굴이어도 그 두 채널은 그대로다.
     */
    expect(turnMood(turn({ discarded: true }))).toBe(turnMood(turn({ failed: true })))
  })

  it('말풍선 표정은 답이면 `guide`, 답이 아니면 `warning`', () => {
    expect(turnMood(turn())).toBe('guide')
    expect(turnMood(turn({ vesselUnresolved: true }))).toBe('guide')
    expect(turnMood(turn({ discarded: true }))).toBe('warning')
  })
})

/**
 * ⚠️ `statusOff`를 인자에서 뺀 전제를 잠근다 (#2009 · #1535).
 *
 * `#2009` 표는 「실패 · 사용 불가」 행에 `stopped`와 `statusOff`를 함께 적었다.
 * 화면에서 둘이 갈리지 않으므로(`setStatusOff`·`setStopped`가 같은 값으로 나란히
 * 불린다) `avatarMood`는 `stopped`만 받는다 — 잉여 인자는 어떤 검사로도 잡히지
 * 않아 조용히 썩는다(실제로 `statusOff`를 넘기지 않게 바꿔도 화면 검사가 전부
 * 초록이었다).
 *
 * 그래서 **전제 쪽을 잠근다.** 둘이 갈리는 날 이 검사가 붉어지고, 그때
 * `avatarMood`가 `statusOff`도 받아야 하는지 다시 보게 된다.
 */
describe('`statusOff`와 `stopped`는 함께 켜진다 (#1535 전제)', () => {
  const SOURCE = readFileSync(
    fileURLToPath(new URL('./AssistantOverlay.tsx', import.meta.url)),
    'utf-8',
  ).replace(/\/\*[\s\S]*?\*\//g, '')

  it('상태 조회가 둘을 같은 값으로 나란히 켠다', () => {
    const pair = /setStatusOff\(!available\)\s*\n\s*setStopped\(!available\)/
    expect(
      pair.test(SOURCE),
      '`setStatusOff(!available)` 바로 뒤에 `setStopped(!available)`가 오지 않습니다 — ' +
        '둘이 갈렸다면 `avatarMood`가 `statusOff`도 받아야 하는지 다시 보세요.',
    ).toBe(true)
  })

  it('`setStatusOff`는 그 한 곳에서만 불린다', () => {
    /*
     * 다른 자리에서 `statusOff`만 켜면 위 짝 검사는 그대로 통과하면서 전제가 깨진다.
     */
    const calls = SOURCE.match(/setStatusOff\(/g) ?? []
    expect(calls.length, `setStatusOff 호출이 ${calls.length}곳입니다 — 한 곳이어야 합니다`).toBe(1)
  })
})
