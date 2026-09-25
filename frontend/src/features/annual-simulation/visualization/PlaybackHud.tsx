import { useEffect, useState } from 'react'
import { DISPLAY_DIGITS, formatDecimalString } from '../../../display/format'
import { probabilityOfDorE, toPercent } from '../annualRules'
import type { AnnualSimulationResult } from '../types'
import type { SimulationPlaybackController, SimulationPlaybackState } from './playbackController'
import type { MapGeometry } from './model'
import { voyageSequenceAtTime, type createVoyageSequence } from './voyageSequencing'
import { SimulationEffects } from './SimulationEffects'
import { routeDisclosure } from '../../map/routeDisclosure'

interface PlaybackHudProps {
  readonly result: AnnualSimulationResult
  readonly projectedYear: string
  readonly vesselName: string
  readonly geometry: Extract<MapGeometry, { readonly status: 'available' }>
  readonly sequence: Extract<ReturnType<typeof createVoyageSequence>, { readonly status: 'available' }>
  readonly controller: SimulationPlaybackController
  readonly suppressEffects: boolean
}

function elapsed(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** 재생값과 서버 최종 결과를 분리해서 보여 주는 읽기 전용 HUD다. */
export function PlaybackHud({ result, projectedYear, vesselName, geometry, sequence, controller, suppressEffects }: PlaybackHudProps) {
  const [state, setState] = useState<SimulationPlaybackState>(() => controller.getState())
  useEffect(() => controller.subscribe(setState), [controller])
  if (state.status === 'unavailable') return null
  const position = voyageSequenceAtTime(sequence, state)
  if (!position) return null
  const route = geometry.routes.find(({ snapshotVoyageId }) => snapshotVoyageId === position.snapshotVoyageId)
  const routeVessel = route?.vesselName?.trim() || vesselName.trim()
  const voyageLabel = position.snapshotVoyageId.trim()
  const { deterministic, monte_carlo: monteCarlo } = result
  const disclosure = route ? routeDisclosure({
    mode: 'playback', source: route.source, kinds: ['DIRECT'], derivation: route.derivation,
  }) : null
  return <aside className="annual-sim__playback-hud" aria-label="항로 재생 정보">
    <section aria-labelledby="annual-playback-domain-heading">
      <h4 id="annual-playback-domain-heading">서버 최종 예측 결과 · 재생 위치와 무관</h4>
      <dl>
        <div><dt>예측 연도</dt><dd>{projectedYear || '미제공'}</dd></div>
        <div><dt>예측 CII</dt><dd>{formatDecimalString(deterministic.projected_attained_cii, DISPLAY_DIGITS.cii)}</dd></div>
        <div><dt>예측 등급</dt><dd>{deterministic.projected_rating}</dd></div>
        <div><dt>목표 등급 달성 확률 ({monteCarlo.target_rating} 이상)</dt><dd>{toPercent(monteCarlo.target_success_probability)}</dd></div>
        <div><dt>D/E 확률</dt><dd>{toPercent(probabilityOfDorE(monteCarlo.rating_probabilities))}</dd></div>
      </dl>
    </section>
    <section aria-labelledby="annual-playback-progress-heading">
      <h4 id="annual-playback-progress-heading">현재 재생 위치 · 시각화 전용</h4>
      <dl>
        <div><dt>항차</dt><dd>{voyageLabel || '미제공'}</dd></div>
        <div><dt>선박</dt><dd>{routeVessel || '미제공'}</dd></div>
        <div><dt>재생 상태</dt><dd>{state.motion === 'playing' ? '재생 중' : '일시정지'}</dd></div>
        <div><dt>재생 경과</dt><dd>{elapsed(state.timeMs)} / {elapsed(state.durationMs)}</dd></div>
        <div><dt>출발</dt><dd>{route?.departureName?.trim() || '미제공'}</dd></div>
        <div><dt>도착</dt><dd>{route?.arrivalName?.trim() || '미제공'}</dd></div>
      </dl>
    </section>
    {disclosure ? <p>{disclosure.visibleText}</p> : null}
    <SimulationEffects simulationId={result.simulation_id} probabilities={result.monte_carlo.rating_probabilities}
      route={route} suppressParticles={suppressEffects} />
  </aside>
}
