import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { readPageMeta } from '../vessel-management/apiProvider'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type {
  ParameterImportResult,
  ParameterImportRowError,
  ParameterKind,
  ParameterRevisionEvent,
} from './revisionRules'

/**
 * 규제 기준값 개정 적재 · 개정 이력 — `API_SPEC §7.5` · `§16.1` (`#1517`).
 *
 * 조회(`apiProvider.ts`)와 파일을 나눈 이유 — 조회는 세 역할 모두가 쓰고 이쪽은
 * 사무직만 쓴다. 한 파일에 섞으면 조회 화면이 쓰기 경로를 함께 끌어온다.
 */

export class RevisionError extends Error {
  /** `403`이면 참 — 역할 또는 둘러보기 정책으로 막힌 것이다. 화면은 서버 문구를 그대로 보인다. */
  readonly forbidden: boolean
  constructor(message: string, options?: { cause?: unknown; forbidden?: boolean }) {
    super(message, options)
    this.name = 'RevisionError'
    this.forbidden = options?.forbidden ?? false
  }
}

export interface RevisionPage {
  events: ParameterRevisionEvent[]
  nextCursor: string | null
}

export interface ParameterRevisionProvider {
  importParameters(
    kind: ParameterKind,
    file: File,
    options: { dryRun: boolean },
  ): Promise<ParameterImportResult>
  listRevisions(cursor?: string | null): Promise<RevisionPage>
}

/** 한 번에 불러오는 이력 수. 개정은 드문 사건이라 첫 화면에 대부분 들어간다. */
export const REVISION_PAGE_SIZE = 20

interface ServerError {
  error?: { message?: string; details?: Array<{ field?: string }> }
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null
}

function toRowErrors(value: unknown): ParameterImportRowError[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const row = asNumber((item as { row?: unknown })?.row)
    const field = asString((item as { field?: unknown })?.field)
    const message = asString((item as { message?: unknown })?.message)
    return row !== null && field !== null && message !== null ? [{ row, field, message }] : []
  })
}

function toEvent(raw: unknown): ParameterRevisionEvent | null {
  const row = raw as Record<string, unknown> | null
  const id = asString(row?.id)
  const timestamp = asString(row?.timestamp)
  if (!row || id === null || timestamp === null) return null
  const details = (row.details ?? {}) as Record<string, unknown>
  const actorRaw = row.actor as { display_name?: unknown; email?: unknown } | null | undefined
  const email = asString(actorRaw?.email)
  return {
    id,
    timestamp,
    kind: asString(row.entity_type) ?? '',
    actor: email !== null ? { displayName: asString(actorRaw?.display_name), email } : null,
    userId: asString(row.user_id),
    importedCount: asNumber(details.imported_count),
    replacedCount: asNumber(details.replaced_count),
    version: asString(details.version),
    sourceRefs: Array.isArray(details.source_refs)
      ? details.source_refs.filter((ref): ref is string => typeof ref === 'string')
      : [],
  }
}

export function createApiParameterRevisionProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): ParameterRevisionProvider {
  async function readFailure(response: Response): Promise<never> {
    if (response.status === 401) {
      redirectToLogin()
      throw new RevisionError(SESSION_EXPIRED_MESSAGE)
    }
    const body = (await response.json().catch(() => null)) as ServerError | null
    throw new RevisionError(
      body?.error?.message ?? `요청을 처리하지 못했습니다 (HTTP ${response.status}).`,
      { forbidden: response.status === 403 },
    )
  }

  return {
    async importParameters(kind, file, options) {
      /*
       * `Content-Type`을 넣지 않는다 — `FormData`를 주면 브라우저가 multipart 경계 문자열까지
       * 붙인다. 손으로 적으면 경계가 빠져 서버가 파싱하지 못한다(`importCsv`와 같다).
       */
      const form = new FormData()
      form.append('file', file)
      form.append('type', kind)
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/parameters/import?dry_run=${options.dryRun}`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
          body: form,
        })
      } catch (cause) {
        throw new RevisionError('서버에 연결하지 못했습니다.', { cause })
      }
      if (!response.ok) return readFailure(response)
      const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null
      const data = body?.data
      const imported = asNumber(data?.imported_count)
      const replaced = asNumber(data?.replaced_count)
      if (!data || imported === null || replaced === null || typeof data.dry_run !== 'boolean') {
        throw new RevisionError('응답 형식이 올바르지 않습니다.')
      }
      return {
        kind: asString(data.table) ?? kind,
        importedCount: imported,
        replacedCount: replaced,
        errors: toRowErrors(data.errors),
        dryRun: data.dry_run,
      }
    },

    async listRevisions(cursor) {
      const query = new URLSearchParams({
        action: 'PARAMETER_IMPORT',
        limit: String(REVISION_PAGE_SIZE),
      })
      if (cursor) query.set('cursor', cursor)
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/audit-logs?${query}`, {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
      } catch (cause) {
        throw new RevisionError('서버에 연결하지 못했습니다.', { cause })
      }
      if (!response.ok) return readFailure(response)
      const body = (await response.json().catch(() => null)) as { data?: unknown } | null
      if (!Array.isArray(body?.data)) throw new RevisionError('응답 형식이 올바르지 않습니다.')
      const events = body.data.flatMap((raw) => {
        const event = toEvent(raw)
        return event ? [event] : []
      })
      return { events, nextCursor: readPageMeta(body).nextCursor }
    },
  }
}
