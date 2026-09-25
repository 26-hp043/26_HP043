import { describe, expect, it } from 'vitest'
import type { AnnualSimulationResult } from '../types'
import { annualProductMapGeometryProvider } from './productMapGeometryProvider'

describe('Annual 제품 지도 provider 경계', () => {
  it('좌표 없는 현행 API에서 mutable 항차를 조합하지 않고 unavailable을 반환한다', async () => {
    const result = { snapshot: { snapshot_id: 'immutable-snapshot' } } as AnnualSimulationResult
    await expect(annualProductMapGeometryProvider.load(result, new AbortController().signal)).resolves.toEqual({
      status: 'unavailable', reason: 'coordinates_not_provided',
    })
  })

  it('취소된 제품 session은 좌표 상태를 만들지 않는다', async () => {
    const abort = new AbortController()
    abort.abort()
    const result = { snapshot: { snapshot_id: 'immutable-snapshot' } } as AnnualSimulationResult
    await expect(annualProductMapGeometryProvider.load(result, abort.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })
})
