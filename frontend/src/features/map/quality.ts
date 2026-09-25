export type MapQualityTier = 'low' | 'medium' | 'high'

export interface MapQualitySignals {
  readonly reducedMotion: boolean
  readonly deviceMemoryGb: number | null
  readonly hardwareConcurrency: number | null
  readonly webgl2: boolean
  readonly maxTextureSize: number | null
}

function browserSignals(): MapQualitySignals {
  const navigatorWithMemory = navigator as Navigator & { readonly deviceMemory?: number }
  const gl = typeof WebGL2RenderingContext === 'undefined'
    ? null
    : document.createElement('canvas').getContext('webgl2')
  return {
    reducedMotion: globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
    deviceMemoryGb: navigatorWithMemory.deviceMemory ?? null,
    hardwareConcurrency: navigator.hardwareConcurrency || null,
    webgl2: gl !== null,
    maxTextureSize: gl ? Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)) : null,
  }
}

/** UA 문자열 없이 공개 capability 신호만으로 결정론적인 품질 단계를 고른다. */
export function mapQualityPolicy(options: {
  readonly override?: MapQualityTier
  readonly signals?: MapQualitySignals
} = {}) {
  const signals = options.signals ?? browserSignals()
  const tier = options.override ?? (
    signals.reducedMotion || signals.deviceMemoryGb !== null && signals.deviceMemoryGb <= 4
      || signals.hardwareConcurrency !== null && signals.hardwareConcurrency <= 4 || !signals.webgl2
      ? 'low'
      : signals.deviceMemoryGb !== null && signals.deviceMemoryGb >= 8
        && signals.hardwareConcurrency !== null && signals.hardwareConcurrency >= 8
        && (signals.maxTextureSize ?? 0) >= 8192 ? 'high' : 'medium'
  )
  if (tier === 'low') return { tier, globe: false, harbor3d: false, pixelRatioCap: 1, buildingStride: 4, animate: false, reason: '기기 성능 또는 움직임 설정에 맞춰 2D 대체 정보를 사용합니다.' }
  if (tier === 'medium') return { tier, globe: true, harbor3d: true, pixelRatioCap: 1.5, buildingStride: 2, animate: !signals.reducedMotion, reason: null }
  return { tier, globe: true, harbor3d: true, pixelRatioCap: 2, buildingStride: 1, animate: !signals.reducedMotion, reason: null }
}
