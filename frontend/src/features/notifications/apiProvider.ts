import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../../api/base'
import type { NotificationItem, NotificationSnapshot } from './types'

/**
 * 알림 조회 — `GET /fleet/notifications` (`API_SPEC §2.19` · #2204).
 *
 * 실패하면 던진다 — 종 버튼이 「불러오지 못했습니다」를 펼친 목록 안에 적는다. 종 버튼
 * 자체는 남는다(셸의 한 자리가 깨져도 화면은 쓸 수 있어야 한다).
 */
export class NotificationsUnavailableError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'NotificationsUnavailableError'
  }
}

interface RawItem {
  kind: NotificationItem['kind']
  level: NotificationItem['level']
  vessel_id: string
  vessel_name: string
  reason: string | null
  days: number | null
  voyage_id: string | null
  voyage_no: string | null
  count: number | null
}

function toItem(raw: RawItem): NotificationItem {
  return {
    kind: raw.kind,
    level: raw.level,
    vesselId: raw.vessel_id,
    vesselName: raw.vessel_name,
    reason: raw.reason,
    days: raw.days,
    voyageId: raw.voyage_id,
    voyageNo: raw.voyage_no,
    count: raw.count,
  }
}

export async function loadNotifications(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<NotificationSnapshot> {
  let response: Response
  try {
    response = await fetchImpl(`${baseUrl}/fleet/notifications`, {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json', ...csrfHeaders() },
    })
  } catch (cause) {
    throw new NotificationsUnavailableError('알림 서버에 연결하지 못했습니다.', { cause })
  }
  if (response.status === 401) {
    redirectToLogin()
    throw new NotificationsUnavailableError(SESSION_EXPIRED_MESSAGE)
  }
  let body: { data?: { counts?: NotificationSnapshot['counts']; items?: RawItem[] } } | null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (!response.ok || !body?.data?.counts || !Array.isArray(body.data.items)) {
    throw new NotificationsUnavailableError('알림을 불러오지 못했습니다.')
  }
  return { counts: body.data.counts, items: body.data.items.map(toItem) }
}
