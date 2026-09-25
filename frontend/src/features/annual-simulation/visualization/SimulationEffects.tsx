import type { Rating } from '../../voyage-cii/types'
import type { SnapshotRouteGeometry } from './model'
import { representativeParticles } from './representativeParticles'

const RATINGS: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

interface SimulationEffectsProps {
  readonly simulationId: string
  readonly probabilities: Readonly<Record<Rating, string>>
  readonly route: SnapshotRouteGeometry | undefined
  readonly suppressParticles: boolean
}

export function SimulationEffects({ simulationId, probabilities, route, suppressParticles }: SimulationEffectsProps) {
  const particles = representativeParticles(simulationId, probabilities)
  const emission = route?.emission
  const relative = emission?.relativeIntensity
  const validRelative = relative !== null && relative !== undefined && Number.isFinite(relative) && relative >= 0 && relative <= 1
  return <section className="annual-sim__effects" aria-labelledby="annual-effects-heading">
    <h4 id="annual-effects-heading">분포·배출 보조 정보</h4>
    <p>대표 점은 등급 확률을 100개로 요약한 분포 시각화이며 실제 Monte Carlo 표본이나 개별 항차가 아닙니다.</p>
    {suppressParticles ? null : <div className="annual-sim__particles" role="img"
      aria-label={`대표 분포 ${particles.length}개: ${RATINGS.map((rating) => `${rating} ${particles.filter((particle) => particle.rating === rating).length}개`).join(', ')}`}>
      {particles.map((particle) => <span key={particle.id} aria-hidden="true"
        className={`annual-sim__particle annual-sim__particle--${particle.rating.toLowerCase()}`}>{particle.rating}</span>)}
    </div>}
    <ul className="annual-sim__particle-legend">
      {RATINGS.map((rating) => <li key={rating}>{rating}: {probabilities[rating]}</li>)}
    </ul>
    {emission ? <section className="annual-sim__emission" aria-label="배출 보조 지표">
      <p>CO₂ {emission.co2Value} {emission.co2Unit}</p>
      {emission.intensityValue && emission.intensityUnit
        ? <p>배출 강도 {emission.intensityValue} {emission.intensityUnit}</p> : null}
      {validRelative ? <div className="annual-sim__emission-scale">
        <span>낮음</span><meter min="0" max="1" value={relative}>상대 강도 {relative}</meter><span>높음</span>
      </div> : null}
      <p>제공된 배출량·상대 강도의 보조 표시이며 물리적 배기가스 농도, CII 등급 또는 규제 판정이 아닙니다.</p>
    </section> : null}
  </section>
}
