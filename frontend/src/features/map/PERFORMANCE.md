# 공용 3D 지도 성능 budget

측정일은 2026-09-25, Node 22/Vite production build 기준이다. 개인정보나 UA 문자열은 품질 판정에 사용하지 않는다.

| 항목 | budget | 현재 production build |
|---|---:|---:|
| 초기 application JS(raw) | 750 KiB 이하 | 726,894 B |
| Harbor loader(raw) | 5 KiB 이하 | 555 B |
| Three shared lazy chunk(raw) | 550 KiB 이하 | 532,581 B |
| Harbor scene(raw) | 100 KiB 이하 | 23,868 B |
| 선박 custom layer(raw) | 10 KiB 이하 | 1,828 B |
| MapLibre adapter(raw) | 100 KiB 이하 | 5,081 B |
| MapLibre shared routeStyles chunk(raw) | 1,100 KiB 이하 | 1,088,350 B |
| desktop frame | p95 16.7 ms 이하(60 FPS 목표) | 브라우저 QA에서 측정 |
| mobile frame | p95 33.3 ms 이하(30 FPS 목표) | 브라우저 QA에서 측정 |

`npm run perf:map`은 production artifact 크기, Three 분리와 MapLibre가 포함된 지배적 shared chunk를 CI에서 검사한다. frame budget은 Performance API로 실제 브라우저에서 10초 구간을 측정한다. 메모리 API는 브라우저별 비표준이므로 강제하지 않고 renderer가 소유한 RAF, listener, ResizeObserver, marker, geometry, material, texture, WebGL context 수가 복귀 후 0인지 lifecycle 테스트로 검사한다.

이 표는 `frontend/scripts/check-map-performance.mjs`의 budget과 함께 갱신한다. 화면별 데이터 의미와 로컬 QA 절차는 [3D 지도 데이터·운영 가이드](../../../../docs/MAP_VISUALIZATION_GUIDE.md), renderer 선택 근거는 [ADR](../../../../docs/ADR_3D_MAP_RENDERING.md)에 둔다.

## 품질 단계

| 단계 | globe | Harbor | pixel ratio | 건물 LOD | 지속 animation |
|---|---|---|---:|---:|---|
| low | Mercator/텍스트 대체 | 로드하지 않음 | 1 | 4개 중 1개 | 없음 |
| medium | 사용 | lazy | 1.5 | 2개 중 1개 | reduced-motion이 아닐 때 |
| high | 사용 | lazy | 2 | 전체 | reduced-motion이 아닐 때 |

판정 신호는 WebGL2, `MAX_TEXTURE_SIZE`, `deviceMemory`, `hardwareConcurrency`, `prefers-reduced-motion`뿐이다. 신호가 없으면 과도하게 high로 올리지 않는다. quality는 표현만 바꾸며 route geometry와 계산값은 바꾸지 않는다.
