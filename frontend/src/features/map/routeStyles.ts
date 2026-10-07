type RouteStyleRole = 'fleet-current' | 'comparison-direct' | 'comparison-detour' | 'playback-traveled' | 'playback-remaining'

interface RouteStyleContract {
  readonly colorToken: '--semantic-info' | '--semantic-primary' | '--color-warning-text'
  readonly width: number
  readonly opacity: number
  readonly dash: readonly number[]
  readonly text: string
}

const STYLES: Readonly<Record<RouteStyleRole, RouteStyleContract>> = {
  'fleet-current': { colorToken: '--semantic-info', width: 2, opacity: 0.9, dash: [2, 1.5], text: '진행 중 항차' },
  // 10/7 — 항로 비교는 두 길을 **한눈에 가르는 것**이 목적이다. 직항은 진한 실선, 우회는 색과 결이 다른 점선.
  'comparison-direct': { colorToken: '--semantic-primary', width: 2.5, opacity: 0.95, dash: [1, 0], text: '직항' },
  'comparison-detour': { colorToken: '--color-warning-text', width: 2, opacity: 0.95, dash: [1.5, 2.2], text: '사용자 경유 우회' },
  'playback-traveled': { colorToken: '--semantic-info', width: 4, opacity: 0.9, dash: [1, 0], text: '진행 구간' },
  'playback-remaining': { colorToken: '--semantic-info', width: 2, opacity: 0.55, dash: [2, 2], text: '잔여 구간' },
}

/** 색과 별개로 dash·width·opacity·텍스트가 mode의 의미를 보존한다. */
export function routeStyle(role: RouteStyleRole): RouteStyleContract {
  return STYLES[role]
}
