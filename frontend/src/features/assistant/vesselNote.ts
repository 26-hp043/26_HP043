import type { ChatAnswer } from './types'

/**
 * 선박 없이 도는 도구 (`#1535`) — `AssistantOverlay`의 「선박을 먼저 골라 주세요」 안내를
 * 붙일지 가른다. 서버 `services/chat_tools.py`의 `run_tool`이 선박 검사
 * **앞에서** 부르는 도구다(「선박 없이도 돈다 — 선종을 말하면 표를 읽는 데 선박은 필요
 * 없다」). 이 도구만으로 값을 낸 답에 위 안내를 붙이면 **틀린 말**이 된다 — 규제값 질문에
 * 선박을 고르지 않고 물었더니 도구가 표를 읽어 제대로 답했는데, 말풍선은 「선박을 먼저
 * 골라 주세요」로 시작했다(09-27 21:40 운영 · Ops inspect `36319818802`). 사용자는 그것을
 * 「선박을 안 골라서 답이 불완전하다」로 읽는다.
 *
 * 계산 도구는 선박이 없으면 오류 봉투를 돌려주지만 **이름은 `tool_calls`에 남는다**
 * (`API_SPEC §15.1` — 「실제로 실행한 도구」). 그래서 「도구가 있었다」가 아니라 **「실행한
 * 도구가 모두 이 목록에 있다」**로 가른다 — 계산을 시도했다가 선박 때문에 못 돈 턴에는
 * 안내가 그대로 붙는다.
 */
export const VESSEL_FREE_TOOLS: ReadonlySet<string> = new Set([
  'lookup_regulation',
  /*
   * `explain_screen_result`도 선박 없이 돈다 (`#1991`). 서버가 *「상단 선박이 없으면(선박
   * 없이 연 화면) 실행의 선박을 따지지 않는다 — 식별자는 어차피 나가지 않는다」*고 적고,
   * `screen_run_id`가 있으면 저장된 결과를 그대로 읽어 **정상 답**을 낸다.
   *
   * ## 닿는 길을 확인했다
   *
   * 세 화면(CII 예측 · 항로 비교 · 연간 등급)은 계산할 때 상단 선박을 채우므로 그 순간에는
   * 조합이 생기지 않는다. 그런데 **계산한 뒤 상단 셀렉트를 「선박 선택 안 함」으로 되돌리면**
   * 결과는 그 주소에 그대로 기억돼 있고(`screenResult.ts`) 상단 선박만 없다 — 그 상태로
   * 물으면 답은 맞는데 말풍선이 「선박을 먼저 골라 주세요」로 시작한다.
   */
  'explain_screen_result',
])

/**
 * 서버가 선박 검사 **앞에서** 부르지만 이 목록에 **의도적으로 넣지 않는** 도구 (`#1991`).
 *
 * `search_vessel`은 선박을 **찾는** 도구다 — 그것만 부른 턴은 아직 선박이 정해지지 않은
 * 턴이므로 「선박을 먼저 골라 주세요」가 맞는 말이다. 목록에서 빠진 것이 실수인지 판단인지
 * 구분되게 이름을 적어 둔다: 아래 대조 검사가 **선박 검사 앞의 도구는 둘 중 한 목록에
 * 있어야 한다**고 보므로, 서버에 새 도구가 생기면 어느 쪽인지 정하지 않고는 지나갈 수 없다.
 */
export const VESSEL_NOTE_STILL_APPLIES: ReadonlySet<string> = new Set(['search_vessel'])

/** 선박을 모르는 턴에 안내를 붙이는가 — 선박 없이 도는 도구만으로 답했으면 붙이지 않는다. */
export function needsVesselNote(answer: Pick<ChatAnswer, 'vesselResolved' | 'discarded' | 'toolCalls'>): boolean {
  if (answer.vesselResolved !== false || answer.discarded) return false
  const tools = answer.toolCalls ?? []
  return !(tools.length > 0 && tools.every((name) => VESSEL_FREE_TOOLS.has(name)))
}
