import type { ChatTurn } from './types'

/**
 * 어시스턴트 아바타의 표정 (`#2009` · `UIFLOW 2-7`).
 *
 * ## 왜 셋인가
 *
 * 이슈는 다섯(`default`·`guide`·`warning`·`thinking`·`celebrate`)을 전제했으나
 * 완성된 캐릭터 32장을 전부 얼굴만 잘라 실제 크기로 재어 보니 **눈은 31장이
 * 전부 같고 입만 둘로 갈렸다**(`#2008`). 30종을 가르는 것은 소품과 몸짓이고,
 * 소품은 얼굴 원 밖이라 40·28px에서 잘린다.
 *
 * - `thinking` 제외 — `default`와 얼굴이 **완전히 같아** 바꿔도 화면에서 보이지 않는다.
 * - `celebrate` 제외 — 보여 줄 조건의 판정 기준이 없다(`#2009` 본문).
 *
 * 눈·입이 다른 5종 얼굴 시안은 `#2067`이 요청했고, 받으면 여기가 다섯으로 돌아간다.
 *
 * ## `pending`을 받지 않는 이유
 *
 * 「작성 중」에 아바타는 **바뀌지 않는다.** 쓸 수 있는 얼굴이 `default`와 같아
 * 바꿔도 아무 변화로 보이지 않으므로, 인자로 받아 무시하면 **읽는 사람이
 * 반영된 줄 안다.** 작성 중은 `PENDING_TEXT`가 말하고, `DESIGN_SYSTEM §8.5`가
 * 정한 채널(접두 문구 · 줄무늬)도 그대로다 — 아바타는 장식이라 구분 채널이 아니다.
 */
export type AvatarMood = 'default' | 'guide' | 'warning'

/** 말풍선 하나의 표정. 답이 아닌 것(폐기 · 실패)은 하나로 묶인다. */
export function turnMood(turn: ChatTurn): AvatarMood {
  return turn.discarded || turn.failed ? 'warning' : 'guide'
}

/**
 * 패널 머리의 표정 = **마지막 어시스턴트 턴**의 표정, 없으면 `default`.
 *
 * 「쓸 수 없음」(`stopped`)은 턴보다 **앞선다** — 답을 하나 받은 뒤에 설정이 꺼지면
 * 머리가 `guide`로 남아 「멀쩡하다」고 말하게 된다.
 *
 * ## `statusOff`를 받지 않는 이유
 *
 * `#2009` 표는 「실패 · 사용 불가」 행에 `stopped`와 `statusOff`를 함께 적었지만,
 * 화면에서 **둘은 갈리지 않는다** — `AssistantOverlay.tsx`의 상태 조회(`#1535`)가
 * `setStatusOff(!available)`와 `setStopped(!available)`를 **같은 값으로 나란히**
 * 부르고, `stopped`는 그 뒤 503에서도 켜지므로 `statusOff ⊆ stopped`다.
 *
 * 받아 두고 무시하지 않고 **빼는** 이유는, 잉여 인자가 검사로 잡히지 않기
 * 때문이다 — 실제로 `statusOff`를 넘기지 않게 바꿔도 화면 검사가 전부 초록이었다.
 * 대신 **그 전제를 `avatarMood.test.ts`가 소스로 잠근다** — 둘이 갈리는 날
 * 그 검사가 먼저 붉어져 여기를 다시 보게 한다.
 */
export function avatarMood(
  turns: readonly ChatTurn[],
  state: { readonly stopped: boolean },
): AvatarMood {
  if (state.stopped) return 'warning'
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const turn = turns[i]
    if (turn.role === 'assistant') return turnMood(turn)
  }
  return 'default'
}
