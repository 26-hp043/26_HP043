import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL, fallbackMessage } from '../../api/base'
import type { AssistantProvider, ChatAnswer, ChatFavorite, ChatHistory, ChatTurn } from './types'

/**
 * 챗봇 provider — `POST /api/v1/chat` (`API_SPEC §15.1` · `#121`).
 *
 * ## 실패가 화면을 죽이지 않는다
 *
 * `PRD §16.2` 장애 격리는 **서버에서만** 성립하는 것이 아니다. 챗봇 호출이
 * 실패했을 때 대시보드가 흔들리면 화면 쪽 격리가 없는 것이다. 그래서 이 provider는
 * **던지되**, 오버레이가 그것을 자기 안에서 받아 말풍선으로 만든다.
 *
 * ## 503을 따로 구분한다
 *
 * 키가 설정되지 않은 상태(`CHAT_UNAVAILABLE`)는 **사용자가 다시 시도해도 소용없다.**
 * 일반 실패와 같은 문구를 쓰면 사용자가 계속 누르게 된다.
 */

export class AssistantError extends Error {
  /** 503 — 챗봇이 설정되지 않았거나 외부 모델이 죽었다. 다시 눌러도 소용없다. */
  readonly unavailable: boolean
  /**
   * 이어 가던 대화가 서버에 없다 (#1981 후속). 다른 탭에서 지웠거나 만료됐다 — 그 번호로는
   * 다시 물어도 같은 404다. 화면이 번호를 버리고 다음 질문부터 새 대화로 시작한다.
   */
  readonly sessionGone: boolean
  /**
   * 별을 달려던 답이 서버에 없다 (#2405 — `PUT /chat/messages/{id}/favorite`의 404). 만료로
   * 지워졌거나 다른 탭에서 대화를 지웠다. 화면이 별 집합·목록을 다시 받는다.
   */
  readonly messageGone: boolean

  constructor(
    message: string,
    options?: { unavailable?: boolean; sessionGone?: boolean; messageGone?: boolean; cause?: unknown },
  ) {
    super(message, { cause: options?.cause })
    this.name = 'AssistantError'
    this.unavailable = options?.unavailable ?? false
    this.sessionGone = options?.sessionGone ?? false
    this.messageGone = options?.messageGone ?? false
  }
}

interface ServerData {
  session_id?: string
  answer?: string
  disclaimer?: string
  tool_calls?: string[]
  discarded?: boolean
  vessel_resolved?: boolean
  /** #2405 — 저장된 답 행의 번호. 폐기·실패로 저장되지 않았으면 `null`. */
  message_id?: string | null
}

/** `GET /chat/sessions/{id}/messages`의 항목 하나 (`API_SPEC §15.8`). */
interface ServerMessage {
  role?: string
  content?: string
  discarded?: boolean
  tool_calls?: string[]
  /** #2405 — 저장된 ASSISTANT 행만 문자열이다. USER 항목·폐기 합성 항목은 `null`. */
  message_id?: string | null
}

/** `GET /chat/favorites`의 항목 하나 (#2405). */
interface ServerFavorite {
  session_id?: unknown
  message_id?: unknown
  question?: unknown
  answer?: unknown
  answered_at?: unknown
  expires_at?: unknown
  favorited_at?: unknown
}

/** 서버 항목 → 즐겨찾기 (#2405). 키가 빠졌거나 타입이 다르면 `null` — 호출부가 던진다. */
function toFavorite(item: ServerFavorite): ChatFavorite | null {
  const { session_id, message_id, question, answer, answered_at, expires_at, favorited_at } = item
  if (
    typeof session_id !== 'string' ||
    typeof message_id !== 'string' ||
    !(question === null || typeof question === 'string') ||
    typeof answer !== 'string' ||
    typeof answered_at !== 'string' ||
    typeof expires_at !== 'string' ||
    typeof favorited_at !== 'string'
  ) {
    return null
  }
  return {
    sessionId: session_id,
    messageId: message_id,
    question,
    answer,
    answeredAt: answered_at,
    expiresAt: expires_at,
    favoritedAt: favorited_at,
  }
}

/**
 * 서버 항목 → 말풍선 (`#1981`). 서버는 역할을 저장 형태(`USER` · `ASSISTANT`)로 준다.
 *
 * 버린 답에는 도구를 싣지 않는다 — 처음 그릴 때(`AssistantOverlay.send`)와 같은 규칙이다
 * (`#1818` — 답이 아닌 것에 근거를 달면 답으로 읽힌다). 서버도 빈 목록을 주지만 화면
 * 규칙을 서버 값에 기대지 않는다.
 */
function toTurn(message: ServerMessage): Omit<ChatTurn, 'id'> | null {
  const role = message.role === 'USER' ? 'user' : message.role === 'ASSISTANT' ? 'assistant' : null
  if (role === null || typeof message.content !== 'string') return null
  if (role === 'user') return { role, text: message.content }
  const discarded = message.discarded === true
  return {
    role,
    text: message.content,
    discarded,
    toolCalls: discarded ? undefined : (message.tool_calls ?? []),
    // #2405 — 버린 답에는 번호가 있어도 싣지 않는다. 답이 아닌 것에 별을 달 수 없다.
    ...(!discarded && typeof message.message_id === 'string' ? { messageId: message.message_id } : {}),
  }
}

export function createApiAssistantProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): AssistantProvider {
  return {
    /*
     * #1535 — 패널을 열 때 한 번 묻는다. **실패는 던진다** — 모르는 상태를 「쓸 수 없음」으로
     * 바꾸면 서버가 잠깐 흔들린 것만으로 사용자가 챗봇이 없는 줄 안다. 401도 여기서는
     * 로그인으로 보내지 않는다 — 질문 경로(`ask`)가 이미 그 일을 한다.
     */
    async status() {
      const response = await fetchImpl(`${baseUrl}/chat/status`, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new AssistantError(fallbackMessage('상태를 확인하지 못했습니다.', response.status))
      const body = (await response.json()) as { data?: { available?: unknown } }
      if (typeof body.data?.available !== 'boolean') {
        throw new AssistantError('응답 형식이 올바르지 않습니다.')
      }
      return { available: body.data.available }
    },

    async ask({ message, sessionId, vesselId, calculationRunId }): Promise<ChatAnswer> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/chat`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            ...csrfHeaders(),
          },
          body: JSON.stringify({
            message,
            ...(sessionId ? { session_id: sessionId } : {}),
            ...(vesselId ? { vessel_id: vesselId } : {}),
            ...(calculationRunId ? { calculation_run_id: calculationRunId } : {}),
          }),
        })
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }

      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }

      const body = (await response.json().catch(() => null)) as {
        data?: ServerData
        error?: { code?: string; message?: string }
      } | null

      if (response.status === 503) {
        throw new AssistantError(
          body?.error?.message ?? '챗봇을 사용할 수 없습니다.',
          { unavailable: true },
        )
      }
      if (!response.ok) {
        throw new AssistantError(
          body?.error?.message ?? fallbackMessage('답변을 받지 못했습니다.', response.status),
          // 대화 번호를 실어 보낸 질문의 404는 「그 대화가 없다」다(`API_SPEC §15.1`).
          { sessionGone: response.status === 404 && Boolean(sessionId) },
        )
      }

      const data = body?.data
      /*
       * ⚠️ `disclaimer`가 없으면 **오류로 만든다.** `#120` 완료 기준이 「모든 응답에
       * disclaimer」이고, 없는 채로 말풍선을 그리면 화면은 깨지지 않고 **면책만
       * 사라진다.** 그건 눈으로 알아채기 어려운 결함이다.
       */
      if (!data?.answer || !data.disclaimer || !data.session_id) {
        throw new AssistantError('응답 형식이 올바르지 않습니다.')
      }

      return {
        sessionId: data.session_id,
        answer: data.answer,
        disclaimer: data.disclaimer,
        toolCalls: data.tool_calls ?? [],
        discarded: data.discarded === true,
        vesselResolved: data.vessel_resolved === true,
        ...(typeof data.message_id === 'string' ? { messageId: data.message_id } : {}),
      }
    },

    /*
     * #1981 — 저장된 대화를 다시 불러온다. **404는 `null`이다** — 남의 것·만료된 것·없는 것을
     * 서버가 같은 코드로 답하므로(`API_SPEC §15.4`) 화면은 어느 쪽인지 모르고, 알 필요도 없다.
     * 셋 다 「이 번호로는 이어 갈 수 없다」이며 새 대화로 시작한다.
     */
    async history(sessionId): Promise<ChatHistory | null> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }
      if (response.status === 404) return null
      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }
      const body = (await response.json().catch(() => null)) as {
        data?: { session_id?: string; messages?: ServerMessage[]; disclaimer?: string }
        error?: { message?: string }
      } | null
      if (!response.ok) {
        throw new AssistantError(
          body?.error?.message ?? '대화를 불러오지 못했습니다.',
        )
      }
      const data = body?.data
      /*
       * `disclaimer`가 없으면 오류다 — `ask`와 같은 이유. 되살린 답 아래에 면책이 빠지면
       * 화면은 깨지지 않고 면책만 사라진다.
       */
      if (!data?.session_id || !data.disclaimer || !Array.isArray(data.messages)) {
        throw new AssistantError('응답 형식이 올바르지 않습니다.')
      }
      const turns: Omit<ChatTurn, 'id'>[] = []
      for (const message of data.messages) {
        const turn = toTurn(message)
        if (turn === null) throw new AssistantError('응답 형식이 올바르지 않습니다.')
        turns.push(turn)
      }
      return { sessionId: data.session_id, turns, disclaimer: data.disclaimer }
    },

    /*
     * #1981 — 「대화 지우기」. 204가 성공이고 **404도 성공으로 본다** — 지우려던 것이 이미
     * 없다(만료 청소 · 다른 탭에서 지움). 그 밖은 던지고 오버레이가 말풍선으로 만든다.
     */
    async forget(sessionId): Promise<void> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/chat/sessions/${encodeURIComponent(sessionId)}`, {
          method: 'DELETE',
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
        })
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }
      if (response.status === 204 || response.status === 404) return
      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }
      const body = (await response.json().catch(() => null)) as {
        error?: { message?: string }
      } | null
      throw new AssistantError(
        body?.error?.message ?? '대화를 지우지 못했습니다.',
      )
    },

    /*
     * #2405 — 내 즐겨찾기 목록. 둘러보기 계정은 서버가 빈 목록을 준다. 항목 하나라도 형식이
     * 어긋나면 던진다 — 일부만 그리면 사용자는 빠진 별을 「지워졌다」로 읽는다.
     */
    async favorites(): Promise<readonly ChatFavorite[]> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/chat/favorites`, {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }
      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }
      const body = (await response.json().catch(() => null)) as {
        data?: { favorites?: ServerFavorite[] }
        error?: { message?: string }
      } | null
      if (!response.ok) {
        throw new AssistantError(body?.error?.message ?? '즐겨찾기를 불러오지 못했습니다.')
      }
      const items = body?.data?.favorites
      if (!Array.isArray(items)) throw new AssistantError('응답 형식이 올바르지 않습니다.')
      const favorites: ChatFavorite[] = []
      for (const item of items) {
        const favorite = toFavorite(item)
        if (favorite === null) throw new AssistantError('응답 형식이 올바르지 않습니다.')
        favorites.push(favorite)
      }
      return favorites
    },

    /* #2405 — 별 달기. 이미 달려 있어도 서버가 200이다(멱등). 404는 「답이 없다」라 `messageGone`으로 던진다. */
    async favorite(messageId): Promise<void> {
      let response: Response
      try {
        response = await fetchImpl(
          `${baseUrl}/chat/messages/${encodeURIComponent(messageId)}/favorite`,
          {
            method: 'PUT',
            credentials: 'include',
            headers: { Accept: 'application/json', ...csrfHeaders() },
          },
        )
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }
      if (response.ok) return
      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }
      const body = (await response.json().catch(() => null)) as {
        error?: { message?: string }
      } | null
      throw new AssistantError(body?.error?.message ?? '즐겨찾기에 넣지 못했습니다.', {
        messageGone: response.status === 404,
      })
    },

    /*
     * #2405 — 별 떼기. 204가 성공이고 **404도 성공으로 본다** — 답이 만료·삭제로 이미 없으면
     * 떼려던 별도 함께 없다(`forget`과 같은 이유).
     */
    async unfavorite(messageId): Promise<void> {
      let response: Response
      try {
        response = await fetchImpl(
          `${baseUrl}/chat/messages/${encodeURIComponent(messageId)}/favorite`,
          {
            method: 'DELETE',
            credentials: 'include',
            headers: { Accept: 'application/json', ...csrfHeaders() },
          },
        )
      } catch (cause) {
        throw new AssistantError('서버에 연결하지 못했습니다.', { cause })
      }
      if (response.status === 204 || response.status === 404) return
      if (response.status === 401) {
        redirectToLogin()
        throw new AssistantError(SESSION_EXPIRED_MESSAGE)
      }
      const body = (await response.json().catch(() => null)) as {
        error?: { message?: string }
      } | null
      throw new AssistantError(body?.error?.message ?? '즐겨찾기에서 빼지 못했습니다.')
    },
  }
}
