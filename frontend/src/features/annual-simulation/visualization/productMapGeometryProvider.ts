import type { AnnualMapGeometryProvider } from './model'

/**
 * 현재 API_SPEC §6.1·§6.3에는 immutable snapshot에 결부된 좌표가 없다.
 * mutable voyage/항만 좌표를 섞으면 과거 실행의 경로를 가장하게 되므로 unavailable을 명시한다.
 */
export const annualProductMapGeometryProvider: AnnualMapGeometryProvider = {
  async load(_result, signal) {
    if (signal.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
    return { status: 'unavailable', reason: 'coordinates_not_provided' }
  },
}
