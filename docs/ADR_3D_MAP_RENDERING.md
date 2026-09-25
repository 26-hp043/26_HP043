# ADR — 3D 지도 renderer와 선박 asset 경계

- 상태: 승인
- 결정일: 2026-09-25
- 관련 이슈: #1432, #1441, #1442

## 맥락

Fleet·Comparison·Annual은 같은 항로·항만 의미와 접근성 대체 정보를 유지해야 한다. 항만은 자유 카메라와 건물·수면이 필요하지만, 전 지구 지도는 MapLibre의 projection·타일·camera를 다시 구현할 이유가 없다. 저장소에는 출처와 재배포 허가를 확인할 수 있는 선박 GLB가 없다.

production build의 현재 실측값과 budget은 [성능 가이드](../frontend/src/features/map/PERFORMANCE.md)를 단일 기록 위치로 사용한다. `@react-three/fiber`와 `@react-three/drei`는 설치되어 있지 않으며 어느 chunk에도 필요하지 않다.

## 검토한 선택지

1. MapLibre + DOM/SVG marker: camera·projection 동기화가 필요 없고 keyboard/ARIA가 직접 유지된다. 다중 선박과 항만 action의 정본이다.
2. MapLibre custom layer + Three.js: MapLibre WebGL context와 camera matrix를 공유할 수 있다. 3D 선박 형상에만 제한하면 별도 canvas/context가 없고 frame마다 React render하지 않는다.
3. 독립 React Three Fiber scene: 지도와 camera·projection·hit target을 이중 관리하고 WebGL context도 하나 더 필요하다. 현 범위에서는 선택하지 않는다.

## 결정

- 전 지구 지도는 MapLibre globe, 항만·선박의 accessible action은 DOM/SVG marker를 정본으로 유지한다.
- 3D 선박은 `vesselLayer.ts`를 지도 load 뒤 dynamic import하는 Three custom layer로만 보강한다. MapLibre가 제공한 WebGL context와 model-view-projection matrix를 공유한다.
- 항만은 기존 `harborRenderer.ts` lazy boundary 뒤의 standalone Three scene을 유지한다. OrbitControls·자체 camera가 필요한 범위가 항만에 한정되기 때문이다.
- reduced-motion/low tier 또는 WebGL/Three 실패 시 DOM/SVG와 구조화 대체 정보가 남는다. 좌표나 heading 결측은 추정하지 않는다.
- GLB는 채택하지 않는다. 합법적 자산이 저장소에 들어오고 출처·재배포 라이선스·축·단위·budget을 함께 검증하기 전에는 loader도 추가하지 않는다.

## 선박 geometry·LOD 계약

선박은 저장소가 소유한 절차형 `ConeGeometry`를 사용한다. 외부 asset·texture·NOTICE 의무가 없다. `+Y`가 선수, 단위는 meter, 원점은 수면 중앙이다. 서버 `course_deg` 또는 playback route bearing만 적용한다.

| 용도 | 삼각형 상한 | texture | asset 파일 |
|---|---:|---:|---:|
| Fleet 다중 선박 | 24 | 0 B | 0 B |
| 단일 추적 확장 상한 | 48 | 0 B | 0 B |

Comparison은 현재 선박 위치 정본이 없으므로 항로·항만만 표시한다. 공용 layer 입력은 `comparison` mode를 허용하지만 좌표를 만들어 선박을 추가하지 않는다.

## 자원 정리와 검증

- layer 제거 시 mesh를 scene에서 분리하고 geometry/material/WebGLRenderer를 dispose한다.
- 비동기 import 완료 전에 unmount되면 layer를 추가하지 않는다.
- renderer callback 변경은 map session을 재생성하지 않는다.
- architecture test는 제품 화면의 MapLibre/Three 직접 import 금지와 두 Three 구현의 lazy boundary를 지킨다.
- `check-map-performance.mjs`, Playwright desktop/mobile smoke, WebGL·PMTiles·Harbor 실패 시나리오를 회귀 기준으로 둔다.

화면별 데이터 의미, 라이선스와 로컬 QA 절차는 [3D 지도 데이터·운영 가이드](MAP_VISUALIZATION_GUIDE.md)에 기록한다.
