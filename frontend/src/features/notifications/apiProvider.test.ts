import { describe, expect, it, vi } from 'vitest'
import { loadNotifications, NotificationsUnavailableError } from './apiProvider'

/** `GET /fleet/notifications` (`API_SPEC §2.19` · #2204) — 서버 모양을 화면 타입으로. */
describe('loadNotifications', () => {
  it('snake_case를 화면 타입으로 옮기고 순서를 바꾸지 않는다', async () => {
    const body = {
      data: {
        counts: { risk: 1, check: 1, total: 2 },
        items: [
          { kind: 'D_ENTRY_SOON', level: 'RISK', vessel_id: 'v2', vessel_name: '나선', reason: null, days: 9, voyage_id: null, voyage_no: null, count: null },
          { kind: 'UNCONFIRMED_VOYAGE', level: 'CHECK', vessel_id: 'v1', vessel_name: '가선', reason: null, days: null, voyage_id: 'y1', voyage_no: '2026-01', count: null },
        ],
      },
    }
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response)
    const result = await loadNotifications(fetchImpl, '/api/v1')
    expect(fetchImpl).toHaveBeenCalledWith('/api/v1/fleet/notifications', expect.anything())
    expect(result.counts.total).toBe(2)
    expect(result.items.map((i) => i.vesselId)).toEqual(['v2', 'v1'])
    expect(result.items[1]).toMatchObject({ voyageId: 'y1', voyageNo: '2026-01' })
  })

  it('실패하면 던진다', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response)
    await expect(loadNotifications(fetchImpl, '/api/v1')).rejects.toBeInstanceOf(NotificationsUnavailableError)
  })

  it('연결이 안 되면 던진다', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network')
    })
    await expect(loadNotifications(fetchImpl, '/api/v1')).rejects.toBeInstanceOf(NotificationsUnavailableError)
  })
})
