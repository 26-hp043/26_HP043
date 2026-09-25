type RouteStyleRole = 'fleet-current' | 'comparison-direct' | 'comparison-detour' | 'playback-traveled' | 'playback-remaining'

interface RouteStyleContract {
  readonly colorToken: '--semantic-info'
  readonly width: number
  readonly opacity: number
  readonly dash: readonly number[]
  readonly text: string
}

const STYLES: Readonly<Record<RouteStyleRole, RouteStyleContract>> = {
  'fleet-current': { colorToken: '--semantic-info', width: 2, opacity: 0.9, dash: [2, 1.5], text: '진행 중 항차' },
  'comparison-direct': { colorToken: '--semantic-info', width: 2, opacity: 0.9, dash: [2, 1.5], text: '직항' },
  'comparison-detour': { colorToken: '--semantic-info', width: 2, opacity: 0.9, dash: [0.5, 2], text: '사용자 경유 우회' },
  'playback-traveled': { colorToken: '--semantic-info', width: 4, opacity: 0.9, dash: [1, 0], text: '진행 구간' },
  'playback-remaining': { colorToken: '--semantic-info', width: 2, opacity: 0.55, dash: [2, 2], text: '잔여 구간' },
}

/** 색과 별개로 dash·width·opacity·텍스트가 mode의 의미를 보존한다. */
export function routeStyle(role: RouteStyleRole): RouteStyleContract {
  return STYLES[role]
}
