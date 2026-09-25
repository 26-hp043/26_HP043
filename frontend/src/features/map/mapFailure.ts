type MapFailureKind = 'pmtiles' | 'webgl' | 'three' | 'glb' | 'route' | 'renderer'

export interface MapFailure {
  readonly kind: MapFailureKind
  readonly message: string
  readonly action: string
}

/** 엔진별 예외 문자열을 화면에서 쓸 수 있는 안정적인 실패 분류로 바꾼다. */
export function classifyMapFailure(error: Error): MapFailure {
  const value = `${error.name} ${error.message}`.toLowerCase()
  if (value.includes('pmtiles') || value.includes('asset-missing')) return { kind: 'pmtiles', message: '지도 타일을 불러오지 못했습니다.', action: '개략도로 위치를 확인하거나 다시 시도해 주세요.' }
  if (value.includes('webgl')) return { kind: 'webgl', message: '이 환경에서 3D 지도를 표시할 수 없습니다.', action: '2D 대체 정보로 확인하거나 다시 시도해 주세요.' }
  if (value.includes('glb') || value.includes('gltf')) return { kind: 'glb', message: '3D 선박 모형을 불러오지 못했습니다.', action: '선박 표식으로 같은 위치를 표시합니다.' }
  if (value.includes('three') || value.includes('항만')) return { kind: 'three', message: '3D 항만 장면을 표시하지 못했습니다.', action: '전체 항로로 돌아가거나 다시 시도해 주세요.' }
  if (value.includes('route')) return { kind: 'route', message: '항로선을 불러오지 못했습니다.', action: '출발·도착 정보는 아래 대체 정보에서 확인할 수 있습니다.' }
  return { kind: 'renderer', message: '지도를 표시하지 못했습니다.', action: '대체 정보를 확인하거나 다시 시도해 주세요.' }
}
