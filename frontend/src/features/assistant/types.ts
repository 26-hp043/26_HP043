/** 챗봇 오버레이 타입 (`#121` · `UIFLOW 2-7`). */

/** 화면에 보이는 말풍선 하나. */
export interface ChatTurn {
  /** 화면이 목록 key로 쓴다. 서버 id가 아니다 — 서버는 메시지 id를 응답에 싣지 않는다. */
  readonly id: string
  readonly role: 'user' | 'assistant'
  readonly text: string
  /**
   * ⚠️ **버려진 답이다** (`API_SPEC §15.2`).
   *
   * 화면이 이것을 **다르게 보여야 한다** — 같은 모양으로 두면 사용자는 「답을
   * 받았다」고 읽는다. 받은 것은 답이 아니라 「답을 못 드린 이유」다.
   */
  readonly discarded?: boolean
}

export interface ChatAnswer {
  readonly sessionId: string
  readonly answer: string
  readonly disclaimer: string
  readonly toolCalls: readonly string[]
  readonly discarded: boolean
}

export interface AssistantProvider {
  ask(input: {
    message: string
    sessionId?: string
    vesselId?: string
  }): Promise<ChatAnswer>
}
