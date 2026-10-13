import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL, fallbackMessage } from '../../api/base'
import type { AssistantProvider, ChatAnswer, ChatHistory, ChatTurn } from './types'

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

  constructor(message: string, options?: { unavailable?: boolean; cause?: unknown }) {
    super(message, { cause: options?.cause })
    this.name = 'AssistantError'
    this.unavailable = options?.unavailable ?? false
  }
}

interface ServerData {
  session_id?: string
  answer?: string
  disclaimer?: string
  tool_calls?: string[]
  discarded?: boolean
  vessel_resolved?: boolean
}

/** `GET /chat/sessions/{id}/messages`의 항목 하나 (`API_SPEC §15.8`). */
interface ServerMessage {
  role?: string
  content?: string
  discarded?: boolean
  tool_calls?: string[]
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
  }
}
