/** 챗봇 오버레이 타입 (`#121` · `UIFLOW 2-7`). */

/** 화면에 보이는 말풍선 하나. */
export interface ChatTurn {
  /** 화면이 목록 key로 쓴다. 서버 번호가 아니다 — 서버 번호는 아래 `messageId`다. */
  readonly id: string
  /**
   * 서버에 저장된 답 행의 번호 (#2405 — `POST /chat`·`GET /chat/sessions/{id}/messages`의
   * `message_id`). 즐겨찾기(별)가 이 번호로 간다. 저장된 답에만 있다 — 사용자 턴 · 버린 답 ·
   * 호출 실패에는 없고, 그런 말풍선에는 별을 그리지 않는다.
   */
  readonly messageId?: string
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
  /**
   * 이 답의 값을 낸 서버 도구들 (#1818 · `API_SPEC §15.1`).
   *
   * 화면이 근거 칩으로 적는다 — `§20 O-12` No-Compute가 「값을 지어내지 않고
   * 계산이 낸 값을 인용한다」이므로, **무엇이 냈는지**가 보이는 쪽이 그 조항에 맞다.
   * 버린 답·실패에는 싣지 않는다(답이 아닌 것에 근거를 달면 답으로 읽힌다).
   */
  readonly toolCalls?: readonly string[]
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
  /** #2405 — 저장된 답 행의 번호. 버린 답처럼 저장되지 않았으면 없다(서버 `null`). */
  readonly messageId?: string
}

/**
 * 즐겨찾기한 답 하나 — `GET /chat/favorites` 항목 (#2405).
 *
 * `question`은 그 답 바로 앞의 질문이다. 서버에 없으면 `null`이다.
 * `expiresAt`은 대화가 지워지는 날이다 — 별은 대화와 함께 지워진다(90일).
 */
export interface ChatFavorite {
  readonly sessionId: string
  readonly messageId: string
  readonly question: string | null
  readonly answer: string
  readonly answeredAt: string
  readonly expiresAt: string
  readonly favoritedAt: string
}

/**
 * 서버에 저장된 대화 하나 — `GET /chat/sessions/{id}/messages` (`API_SPEC §15.8` · `#1981`).
 *
 * `turns`는 화면이 처음 그렸던 말풍선과 같은 성질을 갖는다 — 버린 답은 `discarded`,
 * 답을 낸 도구는 `toolCalls`. `id`는 provider가 붙이지 않는다(화면의 목록 key는 화면이 만든다).
 */
export interface ChatHistory {
  readonly sessionId: string
  readonly turns: readonly Omit<ChatTurn, 'id'>[]
  readonly disclaimer: string
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
    /** #1533 — 화면이 방금 낸 계산 결과의 실행 id. 서버 도구가 저장된 결과를 읽는다. */
    calculationRunId?: string
  }): Promise<ChatAnswer>
  /**
   * 저장된 대화를 다시 불러온다 (`#1981`). 선택 항목이다 — 없으면 오버레이는 복원하지 않는다.
   *
   * **없는·남의·만료된 대화는 `null`이다**(서버 404 · `API_SPEC §15.4`와 같은 코드).
   * 그 밖의 실패는 던진다 — 오버레이는 어느 쪽이든 새 대화로 시작하고 기억한 번호를 지운다.
   */
  history?(sessionId: string): Promise<ChatHistory | null>
  /**
   * 대화를 지운다 — `DELETE /chat/sessions/{id}` (`API_SPEC §15.6` · `#1330`). 선택 항목이다.
   * 이미 없는 대화(404)도 **성공으로 본다** — 지우려던 것이 없는 상태가 곧 원하던 상태다.
   */
  forget?(sessionId: string): Promise<void>
  /**
   * 내 즐겨찾기 목록 — `GET /chat/favorites` (#2405). 최근에 단 것이 앞이다. 선택 항목이다 —
   * 없으면 오버레이는 별·목록 버튼도 그리지 않는다. 실패는 던진다.
   */
  favorites?(): Promise<readonly ChatFavorite[]>
  /** 별 달기 — `PUT /chat/messages/{id}/favorite` (#2405). 이미 달려 있어도 성공이다. */
  favorite?(messageId: string): Promise<void>
  /**
   * 별 떼기 — `DELETE /chat/messages/{id}/favorite` (#2405). 별이 없어도 성공이다.
   * 404(답이 이미 지워졌다)도 성공으로 본다 — 떼려던 별이 이미 없다(`forget`과 같은 이유).
   */
  unfavorite?(messageId: string): Promise<void>
}
