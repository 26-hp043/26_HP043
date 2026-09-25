# 3D 지도 데이터·운영 가이드

이 문서는 현재 구현의 데이터 의미와 로컬 검증 방법을 설명하는 비정본 운영 가이드다. 제품 범위와 문구의 정본은 `PRD.md`, API 계약은 `API_SPEC.md`, 화면 표현은 `DESIGN_SYSTEM.md`를 따른다.

## 화면별 데이터 경계

| 화면 | renderer | 표시하는 사실 | 표시하지 않는 사실 |
|---|---|---|---|
| Fleet | MapLibre globe + DOM/SVG marker | API가 준 선박의 **현재 위치 스냅샷**, 등급·방위·운항 상태, 표시용 SeaRoute | 시간에 따른 실제 이동. 이동 이력이 없으므로 Fleet 선박은 정적이다 |
| Comparison | 독립 comparison adapter + MapLibre globe | 사용자가 고른 출발·도착과 직항/우회 조건으로 조회한 표시용 SeaRoute | 선박의 현재 위치, 실제 운항 궤적, 확정된 항해 계획 |
| Annual | `AnnualMapGeometryProvider` + playback renderer | 같은 결과 snapshot에 속한 명시적 좌표와 재생 metadata | 현재 API에 없는 좌표를 추정한 지도·재생. provider가 `unavailable`이면 기존 결과 UI만 남는다 |
| Harbor | 진입할 때만 불러오는 Three.js scene | 부산 북항·싱가포르 항만 OSM 스냅샷의 건물·도로와 연출용 수면·선박 | 정확한 접안 위치, 수심, 항해 가능성, 측량·항법 정보 |

Fleet의 현재 위치와 Annual playback은 서로 다른 계약이다. Fleet에 이동 이력이 없을 때 시각적 효과를 위해 선박을 움직이지 않는다. 움직임 검증은 명시적 fixture를 쓰는 Annual 장면에서만 한다.

## 항로와 거리의 의미

- `SEAROUTE`는 Eurostat SeaRoute 경로망을 이용한 **표시용 geometry**다. 화면에 보이는 선의 길이는 서버의 CII 계산 거리나 연간 시뮬레이션 입력을 바꾸지 않는다.
- Comparison의 `DIRECT`/`DETOUR`는 사용자 비교 조건이다. `DETOUR` 경유점을 실제 선박의 계획 waypoint로 해석하지 않는다.
- `WAYPOINT`는 provider가 순서와 좌표를 명시해 전달한 planned route만 뜻한다. 표시용 SeaRoute 및 Comparison 우회와 구분하며, AIS 실제 운항 궤적이나 운항 완료 기록이라는 뜻이 아니다.
- SeaRoute 조회가 실패하면 대권선(`GREAT_CIRCLE`)이나 직선으로 대체하지 않는다. 좌표·source가 없거나 유효하지 않으면 경로를 만들지 않는다.
- 화면 geometry는 실제 항해 계획이 아니며 항만 진입, 육지 회피, 수심 또는 접안 안전성을 보증하지 않는다.

즉 **표시용 경로**, **CII 계산 거리**, **계획 waypoint**, **AIS 실제 궤적**은 네 개의 독립된 데이터다. 한 종류를 다른 종류로 추정하거나 재계산하지 않는다.

## HarborScene의 정확도 한계

항만 JSON은 OSM building footprint와 도로를 보존한다. `height` 태그는 OSM 기록값, `building:levels`는 층당 3 m 추정, 태그가 없으면 시각화용 결정적 fallback 높이다. 현재 renderer는 footprint의 bounding box를 단순 상자로 만들고 높이를 축소·제한하므로 실제 건물 형상이나 높이 모델이 아니다.

수면은 bathymetry나 해안 polygon이 아니라 평면으로 연출한다. 장면의 절차형 선박도 실제 berth 좌표에 놓인 선박이 아니다. 따라서 접안 계획, 수심 판단, 충돌 회피나 항해 안전 용도로 사용할 수 없다. 원본 범위·높이 변환·재생성 절차는 [항만 스냅샷 README](../frontend/public/harbor/README.md)에 기록되어 있다.

## 출처와 라이선스

| 데이터·asset | 화면 표시 | 추적 위치 |
|---|---|---|
| OpenStreetMap basemap/항만 스냅샷 | `© OpenStreetMap contributors` | [NOTICE](../NOTICE), [항만 README](../frontend/public/harbor/README.md), 각 Harbor JSON의 `metadata` |
| Eurostat SeaRoute 및 searoute-py | 경로 attribution과 라이선스 | [NOTICE](../NOTICE), renderer의 route source disclosure |
| 절차형 선박 geometry | 외부 texture/GLB 없음 | [선박 asset notice](../frontend/src/features/map/VESSEL_ASSET_NOTICE.md) |

OSM 파생 데이터베이스는 ODbL 1.0, Eurostat SeaRoute 데이터는 EUPL-1.2, searoute-py는 Apache-2.0 조건을 따른다. 화면 attribution을 제거하지 않는다.

## 장애·접근성·성능

- PMTiles 또는 WebGL 실패 시 Mercator/SVG/구조화 텍스트 대체 정보로 내려가며, 경로 실패는 성공한 다른 선이나 화면을 무너뜨리지 않는다.
- Harbor lazy load 실패 시 텍스트 한계 안내와 retry를 제공한다. 퇴장·retry 때 RAF, listener, observer, geometry, material, texture와 WebGL context를 정리한다.
- canvas와 globe는 `aria-describedby`로 같은 위치·항로·한계 요약을 제공한다. marker는 keyboard로 선택할 수 있고 focus를 Harbor 왕복 뒤 복원한다.
- `prefers-reduced-motion`은 자동 playback, follow camera, Harbor 지속 animation을 억제한다. 실행 중 설정 변경도 반영한다.
- low/medium/high 품질은 pixel ratio, LOD와 장식 animation만 바꾼다. route geometry나 계산값은 바꾸지 않는다.
- Three.js Harbor와 3D 선박 layer는 dynamic import 뒤에 두어 최초 application chunk에 포함하지 않는다.

설계 근거는 [3D 지도 ADR](ADR_3D_MAP_RENDERING.md), budget·품질 판정·측정법은 [성능 가이드](../frontend/src/features/map/PERFORMANCE.md)를 따른다.

## 로컬 QA

```sh
cd frontend
npm run dev -- --host 127.0.0.1 --port 4173
```

- 전체 장면: `http://127.0.0.1:4173/map-smoke.html`
- Annual fixture 자동 재생: `http://127.0.0.1:4173/map-smoke.html?autoplay=1#annual-playback-scene`

상단 장면 이동 링크로 Fleet, Comparison, Annual Playback, Harbor를 순서대로 확인한다. 첫 Fleet 선박은 current-position 스냅샷이라 움직이지 않는 것이 정상이다. Annual Playback의 **재생** 버튼으로 명시적 fixture 경로의 이동을 확인한다. `autoplay=1`은 이 smoke fixture에서만, reduced-motion이 아닐 때만 재생하며 제품 Fleet에는 영향을 주지 않는다.

```sh
cd frontend
npm test
npm run lint
npm run build
npm run perf:map
npm run test:map-smoke
```

`test:map-smoke`는 자체 preview 서버를 사용해 desktop과 390 px mobile, reduced-motion, low quality, 실패 fallback, Harbor 왕복의 history·focus·console 오류를 검사한다.
