import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type { AssistantProvider, ChatAnswer } from './types'

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
}

export function createApiAssistantProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): AssistantProvider {
  return {
    async ask({ message, sessionId, vesselId }): Promise<ChatAnswer> {
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
          body?.error?.message ?? `답변을 받지 못했습니다 (HTTP ${response.status}).`,
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
      }
    },
  }
}
