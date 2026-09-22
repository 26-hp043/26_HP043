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
  /**
   * #1243 — 이 턴에서 **선박이 정해지지 않았다**(`vessel_resolved=false`). 답은
   * 왔지만 계산 도구는 선박 없이 못 돌았다는 뜻이다. `discarded`와는 다르다 —
   * 답 자체는 버리지 않았다.
   */
  readonly vesselUnresolved?: boolean
  /**
   * ⚠️ **호출 자체가 실패했다** — 위 `discarded`와 다르다 (`#1051` 3절에서 갈랐다).
   *
   * `discarded`는 **서버가 답을 만들고 폐기한 것**이고, 이것은 **답을 받지 못한
   * 것**이다(연결 실패 · 설정 없음). 종전에는 실패도 `discarded`로 표시해
   * 위 주석의 정의와 코드가 어긋나 있었다 — 접두 문구(확정 ⓐ)를 붙이자
   * 「답을 드리지 못했습니다 — 챗봇을 사용할 수 없습니다.」 같은 겹말이 되어
   * 드러났다.
   *
   * 둘 다 「답이 아니다」라 **줄무늬는 함께 쓰지만**, 접두 문구는 `discarded`에만
   * 붙는다. 실패 쪽 문구는 그 자체로 이미 완결된 문장이다.
   */
  readonly failed?: boolean
}

export interface ChatAnswer {
  readonly sessionId: string
  readonly answer: string
  readonly disclaimer: string
  readonly toolCalls: readonly string[]
  readonly discarded: boolean
  /**
   * 서버가 이 대화의 선박을 알고 있는가 (#1242 · #1243). false이고 폐기도 아니면
   * 「선박을 먼저 골라 주세요」 안내를 함께 보여 준다 — 답은 왔지만 계산은
   * 선박 없이는 못 돌았다는 뜻이다.
   */
  readonly vesselResolved?: boolean
}

export interface AssistantProvider {
  /**
   * 챗봇을 지금 쓸 수 있는가 — `GET /chat/status` (`API_SPEC §15.7` · `#1535`).
   *
   * 선택 항목이다 — 없으면 오버레이는 조회 없이 종전대로 질문 뒤 503으로 안다.
   * 조회 자체가 실패하면 **던진다**. 오버레이는 그것을 「쓸 수 없음」으로 읽지 않는다.
   */
  status?(): Promise<{ readonly available: boolean }>
  ask(input: {
    message: string
    sessionId?: string
    vesselId?: string
  }): Promise<ChatAnswer>
}
