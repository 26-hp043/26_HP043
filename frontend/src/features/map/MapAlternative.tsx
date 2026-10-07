import type { MapFailure } from './mapFailure'
import './MapAlternative.css'

interface MapAlternativeProps {
  readonly id: string
  readonly title: string
  readonly items: readonly string[]
  readonly failure?: MapFailure | null
  readonly onRetry?: () => void
}

/** canvas를 보지 못해도 지도에 담긴 핵심 사실을 읽을 수 있는 구조화 대체 정보다. */
export function MapAlternative({ id, title, items, failure = null, onRetry }: MapAlternativeProps) {
  return <section id={id} className="map-alternative" aria-label={`${title} 대체 정보`}>
    {failure ? <div role="alert" aria-live="assertive">
      <p>{failure.message} {failure.action}</p>
      {onRetry ? <button type="button" onClick={onRetry}>지도 다시 시도</button> : null}
    </div> : null}
    <details open={failure !== null}>
      {/* 보이는 이름은 짧게(10/7), 낭독 이름은 무엇의 텍스트인지까지 */}
      <summary aria-label={`${title} 텍스트 정보`}>텍스트로 보기</summary>
      <ul>{items.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul>
    </details>
  </section>
}
