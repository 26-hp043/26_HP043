import { useCallback, useEffect, useMemo, useState } from 'react'
import { MapRendererHost, type MapRendererEvent } from '../../map/renderer'
import type { AnnualSimulationResult } from '../types'
import { PlaybackControls } from './PlaybackControls'
import type { PlaybackCameraMode } from './followCamera'
import { createVisualizationModel, type AnnualMapGeometryProvider, type MapGeometry } from './model'
import { createVoyageSequence, createVoyageSequencePlaybackController } from './voyageSequencing'
import { PlaybackHud } from './PlaybackHud'
import { MapAlternative } from '../../map/MapAlternative'
import { classifyMapFailure, type MapFailure } from '../../map/mapFailure'
import { useReducedMotion } from '../../map/useReducedMotion'
import { mapQualityPolicy } from '../../map/quality'

type GeometryState =
  | { readonly status: 'loading' }
  | { readonly status: 'unavailable' }
  | { readonly status: 'available'; readonly geometry: Extract<MapGeometry, { readonly status: 'available' }> }
  | { readonly status: 'error'; readonly message: string }

interface AnnualPlaybackProps {
  readonly result: AnnualSimulationResult
  readonly geometryProvider: AnnualMapGeometryProvider
  readonly projectedYear: string
  readonly vesselName: string
  /** deterministic fixture QA 전용. 제품 화면은 전달하지 않아 기본 일시정지를 유지한다. */
  readonly autoPlay?: boolean
}

/** 실제 snapshot 좌표가 주입된 실행에만 제품 playback을 만든다. */
export function AnnualPlayback({ result, geometryProvider, projectedYear, vesselName, autoPlay = false }: AnnualPlaybackProps) {
  const [attempt, setAttempt] = useState(0)
  const [geometryState, setGeometryState] = useState<GeometryState>({ status: 'loading' })
  const [geometryKey, setGeometryKey] = useState<string | null>(null)
  const [rendererAttempt, setRendererAttempt] = useState(0)
  const [rendererStatus, setRendererStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [rendererFailure, setRendererFailure] = useState<MapFailure | null>(null)
  const [cameraMode, setCameraMode] = useState<PlaybackCameraMode>('overview')
  const [viewMode, setViewMode] = useState<'2d' | '2.5d'>('2.5d')
  const [resetViewToken, setResetViewToken] = useState(0)
  const reducedMotion = useReducedMotion()
  const lowQuality = useMemo(() => mapQualityPolicy().tier === 'low', [])
  const loadPlaybackRenderer = useCallback(
    () => import('../../map/playbackRenderer').then(({ playbackRenderer }) => playbackRenderer),
    [],
  )

  useEffect(() => {
    const abort = new AbortController()
    const requestKey = `${result.simulation_id}:${attempt}`
    void geometryProvider.load(result, abort.signal).then((geometry) => {
      if (abort.signal.aborted) return
      const adapted = createVisualizationModel(result, geometry).mapGeometry
      setGeometryState(adapted.status === 'available'
        ? { status: 'available', geometry: adapted }
        : { status: 'unavailable' })
      setGeometryKey(requestKey)
    }, (error: unknown) => {
      if (!abort.signal.aborted) {
        setGeometryState({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        setGeometryKey(requestKey)
      }
    })
    return () => abort.abort()
  }, [attempt, geometryProvider, result])

  // effect가 새 요청을 시작하기 전 렌더에서도 이전 실행의 좌표를 절대 보이지 않는다.
  const currentGeometryState: GeometryState = geometryKey === `${result.simulation_id}:${attempt}`
    ? geometryState
    : { status: 'loading' }

  const sequence = useMemo(() => geometryKey === `${result.simulation_id}:${attempt}` && geometryState.status === 'available'
    ? createVoyageSequence(geometryState.geometry.routes.map((route, snapshotIndex) => ({
        snapshotVoyageId: route.snapshotVoyageId,
        snapshotIndex,
        route,
        playbackDurationMs: route.playbackDurationMs,
        startedAt: route.startedAt,
        endedAt: route.endedAt,
      })))
    : null, [attempt, geometryKey, geometryState, result.simulation_id])
  const controller = useMemo(() => sequence ? createVoyageSequencePlaybackController(sequence) : null, [sequence])
  useEffect(() => () => controller?.destroy(), [controller])
  useEffect(() => {
    if (reducedMotion) controller?.pause()
    else if (autoPlay) controller?.play()
  }, [autoPlay, controller, reducedMotion])

  const onMapEvent = useCallback((event: MapRendererEvent) => {
    if (event.type === 'ready') setRendererStatus('ready')
    if (event.type === 'error') { setRendererStatus('error'); setRendererFailure(classifyMapFailure(event.error)) }
    if (event.type === 'selection' && event.id?.startsWith('camera:')) setCameraMode(event.id.slice(7) as PlaybackCameraMode)
  }, [])

  if (currentGeometryState.status === 'loading') return null
  if (currentGeometryState.status === 'unavailable') return <p className="annual-sim__map-unavailable" role="status">
    이 실행의 스냅샷에는 항로 좌표가 없어 지도와 재생 제어를 표시하지 않습니다.
  </p>
  if (currentGeometryState.status === 'error') return <section className="annual-sim__playback" aria-label="항로 재생">
    <p role="alert">항로 좌표를 불러오지 못했습니다. {currentGeometryState.message}</p>
    <button type="button" onClick={() => setAttempt((value) => value + 1)}>다시 시도</button>
  </section>
  if (!sequence || sequence.status === 'unavailable' || !controller) return null

  const visualization = createVisualizationModel(result, currentGeometryState.geometry)
  const firstRoute = sequence.segments[0].route.coordinates
  const model = {
    ...visualization,
    mode: 'playback' as const,
    route: {
      source: 'provided-coordinates' as const,
      coordinates: firstRoute,
      routeLines: sequence.segments.map((segment) => segment.route.coordinates),
    },
    bearing: 0,
    pitch: viewMode === '2d' ? 0 : 50,
    controller,
    cameraMode,
    resetViewToken,
    reducedMotion,
    // 여러 항차의 속도를 한 값으로 일반화하지 않는다. 단일 항차 truth가 있을 때만 wake를 허용한다.
    speedKnots: currentGeometryState.geometry.routes.length === 1
      ? currentGeometryState.geometry.routes[0].speedKnots
      : null,
  }
  return <section className="annual-sim__playback" aria-label="항로 재생">
    <h3>항로 재생</h3>
    <p id="annual-playback-status" role="status" aria-live="polite">
      {rendererStatus === 'ready' ? '항로 지도가 준비되었습니다.' : rendererStatus === 'error' ? '항로 지도를 표시하지 못했습니다.' : '항로 지도를 불러오는 중입니다.'}
    </p>
    <PlaybackControls controller={controller} cameraMode={cameraMode} onCameraModeChange={setCameraMode}
      onResetView={() => setResetViewToken((value) => value + 1)} viewMode={viewMode} onViewModeChange={setViewMode} />
    <PlaybackHud result={result} projectedYear={projectedYear} vesselName={vesselName}
      geometry={currentGeometryState.geometry} sequence={sequence} controller={controller}
      suppressEffects={reducedMotion || lowQuality} />
    <div className="annual-sim__playback-map">
      <MapRendererHost key={rendererAttempt} ariaLabel="연간 시뮬레이션 snapshot 항로 지도"
        ariaDescribedBy="annual-playback-status annual-playback-alternative" model={model}
        loadRenderer={loadPlaybackRenderer}
        onEvent={onMapEvent} />
    </div>
    <MapAlternative id="annual-playback-alternative" title="연간 항로 재생"
      failure={rendererFailure}
      onRetry={() => { setRendererFailure(null); setRendererStatus('loading'); setRendererAttempt((value) => value + 1) }}
      items={sequence.segments.map((segment, index) => `항차 ${index + 1}: 출발 ${segment.route.coordinates[0].join(', ')} · 도착 ${segment.route.coordinates.at(-1)?.join(', ')}`)} />
  </section>
}
