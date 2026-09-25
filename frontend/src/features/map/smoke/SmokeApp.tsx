import { useState } from 'react'
import { FleetMap } from '../../fleet/FleetMap'
import { PositionChart } from '../../fleet/PositionChart'
import type { FleetVessel } from '../../fleet/types'
import { VoyageRouteMap } from '../../scenario-comparison/VoyageRouteMap'
import { AnnualPlayback } from '../../annual-simulation/visualization/AnnualPlayback'
import type { AnnualSimulationResult } from '../../annual-simulation/types'
import type { AnnualMapGeometryProvider } from '../../annual-simulation/visualization/model'
import { getKnownRouteSource } from '../routeGeometry'

const vessels: FleetVessel[] = [{
  id: 'smoke-1', name: 'BlueLog호', shipType: 'BULK_CARRIER', imoNumber: 'IMO0000001',
  underwayState: 'UNDER_WAY', detailStatus: 'SAILING', lat: '35.1', lon: '129.0333', positionUpdatedAt: '2026-09-25T00:00:00Z',
  route: { departureLat: '35.1', departureLon: '129.0333', arrivalLat: '1.2833', arrivalLon: '103.85', departurePortName: '부산', arrivalPortName: '싱가포르' }, courseDeg: '210',
  isCiiApplicableHint: true, grossTonnage: '50000', dataAvailable: true, unavailableReason: null,
  ytdAttainedCii: '5', ytdRequiredCii: '5', ytdRating: 'C', riskLevel: 'LOW', riskReasons: [], daysToD: 100, daysToDReason: null,
}]
const result: AnnualSimulationResult = {
  simulation_id: 'smoke-simulation', calculation_run_id: 'smoke-run',
  deterministic: { projected_attained_cii: '5', projected_rating: 'C', completed_voyage_count: 1, remaining_voyage_count: 1, completed_M_gco2: '1', completed_W_capacity_nm: '1', planned_M_gco2: '1', planned_W_capacity_nm: '1' },
  monte_carlo: { rng_metadata: { seed_entropy: '1', bit_generator: 'PCG', numpy_version: '2', python_version: '3', platform: 'smoke' }, runs: 1, rating_probabilities: { A: '0', B: '0', C: '1', D: '0', E: '0' }, target_success_probability: '1', target_rating: 'C', p10: '5', p50: '5', p90: '5', mean_cii: '5' },
  risk_level: 'LOW', sensitivity_analysis: { interaction_note: '' }, snapshot: { snapshot_id: 'smoke-snapshot', created_at: '2026-09-25T00:00:00Z', voyage_count: 1 }, warnings: [],
}
const geometryProvider: AnnualMapGeometryProvider = { load: async () => ({ status: 'available', snapshotId: 'smoke-snapshot', routes: [{ snapshotVoyageId: 'smoke-voyage', vesselName: 'BlueLog호', departureName: '부산', arrivalName: '싱가포르', playbackDurationMs: 10_000, coordinates: [[129.0333, 35.1], [120, 20], [103.85, 1.2833]], source: getKnownRouteSource('searoute/marnet')! }] }) }

function FleetSmoke() {
  const [failed, setFailed] = useState(false)
  return failed ? <PositionChart vessels={vessels} /> : <FleetMap vessels={vessels} onRendererError={() => setFailed(true)} />
}

export function SmokeApp() {
  const autoPlay = new URLSearchParams(window.location.search).get('autoplay') === '1'
  // minmax(0, 1fr)는 controls의 intrinsic 폭이 모바일 viewport와 지도 크기를 밀어내지 않게 한다.
  return <main style={{ padding: 16, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 24 }}>
    <h1>지도 visual smoke</h1>
    <nav aria-label="지도 장면 바로가기">
      <a href="#fleet-scene">Fleet 현재 위치</a>{' · '}
      <a href="#comparison-scene">Comparison 항로</a>{' · '}
      <a href="#annual-playback-scene">Annual 움직이는 항로</a>
    </nav>
    <p>Fleet는 현재 위치 snapshot이라 움직이지 않습니다. 선박 이동은 Annual에서 재생 버튼을 누르거나 <a href="?autoplay=1#annual-playback-scene">자동 재생 fixture</a>로 확인하세요.</p>
    <section id="fleet-scene" data-smoke="fleet"><h2>Fleet · 현재 위치 snapshot</h2><FleetSmoke /></section>
    <section id="comparison-scene" data-smoke="comparison"><h2>Comparison · 계획 항로</h2><VoyageRouteMap currentLat="35.1" currentLon="129.0333" destinationLat="1.2833" destinationLon="103.85" destinationName="싱가포르" samplePorts={[{ locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 }, { locode: 'SGSIN', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 }]} /></section>
    <section id="annual-playback-scene" data-smoke="annual"><h2>Annual · 움직이는 snapshot 항로</h2><p>아래 재생 버튼으로 선박 이동을 확인할 수 있습니다.</p><AnnualPlayback result={result} geometryProvider={geometryProvider} projectedYear="2026" vesselName="BlueLog호" autoPlay={autoPlay} /></section>
  </main>
}
