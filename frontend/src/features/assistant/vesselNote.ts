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
export const VESSEL_FREE_TOOLS: ReadonlySet<string> = new Set(['lookup_regulation'])

/** 선박을 모르는 턴에 안내를 붙이는가 — 선박 없이 도는 도구만으로 답했으면 붙이지 않는다. */
export function needsVesselNote(answer: Pick<ChatAnswer, 'vesselResolved' | 'discarded' | 'toolCalls'>): boolean {
  if (answer.vesselResolved !== false || answer.discarded) return false
  const tools = answer.toolCalls ?? []
  return !(tools.length > 0 && tools.every((name) => VESSEL_FREE_TOOLS.has(name)))
}
