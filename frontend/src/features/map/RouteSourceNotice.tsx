import type { RouteSource } from './routeGeometry'
import './RouteSourceNotice.css'

/** 지도 배경(PMTiles)의 출처 — `mapLibreRenderer`의 `protomaps` 소스와 같은 문구다. */
const BASEMAP_ATTRIBUTION = '© OpenStreetMap'

/**
 * 지도 출처를 지도 아래 **펼친 한 줄**로 적는다 (`#1853` ③ · `#1300` 결정 5항).
 *
 * 2026-09-27 디자인 확정 — 「접힌 컨트롤에서 꺼내 화면 하단 한 줄로 · 「© OpenStreetMap」과 같은
 * 줄에」. 그래서 지도의 MapLibre 출처 컨트롤은 끄고(`attributionControl: false`) 이 줄이 출처
 * 표기의 **유일한 자리**다.
 *
 * - 지도 배경의 「© OpenStreetMap」은 **늘** 싣는다 — 지도를 그리면 그 데이터를 쓴다.
 * - 경로망 출처(EUPL-1.2 · Apache-2.0)는 **항로선을 묻는 지도에만** 뒤에 붙인다(`source`).
 *
 * 문구는 `routeGeometry`의 출처 메타데이터 한 곳에서 온다(서버 응답의 자유 문구를 싣지 않는다).
 * 그 컨트롤(`compact`)은 처음에는 펼쳐져 있다가 사용자가 지도를 한 번 끌면 접혔다
 * (`maplibre-gl` `attribution_control.ts` — `drag` 때 `maplibregl-compact-show`를 걷는다).
 */
export function RouteSourceNotice({ source }: { readonly source: RouteSource | null }) {
  return (
    <p className="route-source">
      {source === null ? BASEMAP_ATTRIBUTION : `${BASEMAP_ATTRIBUTION} · ${source.attribution}`}
    </p>
  )
}
