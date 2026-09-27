import type { RouteSource } from './routeGeometry'
import './RouteSourceNotice.css'

/**
 * 경로망 출처를 지도 아래에 **펼친 한 줄**로 적는다 (`#1853` ③ · `#1300` 결정 5항).
 *
 * 결정 5항은 EUPL-1.2(경로망 데이터)·Apache-2.0(`searoute`) 출처를 `README` · `NOTICE` ·
 * **화면 하단** 세 곳에 둔다. 종전에는 지도 오른쪽 아래 MapLibre 출처 컨트롤에만 있었는데,
 * 그 컨트롤(`compact: true`)은 처음에는 펼쳐져 있다가 **사용자가 지도를 한 번 끌면 접힌다**
 * (`maplibre-gl` `attribution_control.ts` — `drag` 때 `maplibregl-compact-show`를 걷는다).
 * 접힌 뒤에는 ⓘ를 눌러야 보여, 결정문의 「화면 하단」을 채우지 못했다.
 *
 * 컨트롤 안의 표기는 그대로 둔다 — 지도 타일과 같은 자리에서 출처를 모으는 것이 MapLibre의
 * 방식이고, 이 줄은 그것을 대신하지 않고 보탠다. 문구는 `routeGeometry`의 출처 메타데이터
 * 하나에서 온다(서버 응답의 자유 문구를 싣지 않는다).
 *
 * ⚠️ 자리·모양은 개발 임시안이다 — `rlatnals4114` 검토 대상(`DESIGN_SYSTEM §9.5` · `#1853`).
 */
export function RouteSourceNotice({ source }: { readonly source: RouteSource }) {
  return <p className="route-source">{source.attribution}</p>
}
