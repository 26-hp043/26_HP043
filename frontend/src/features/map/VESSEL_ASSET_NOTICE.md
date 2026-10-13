# 3D 선박 asset notice

현재 3D 선박은 `vesselLayer.ts`가 만드는 저장소 소유 절차형 geometry다. 외부 GLB, texture, 저작자 asset을 포함하지 않으므로 별도 제3자 NOTICE 항목이 없다.

외부 asset을 추가할 때에는 파일과 같은 변경에서 출처, 원 라이선스, 재배포 허용 조항, 수정 여부, forward axis, 단위, 원점, polygon·texture·파일 크기를 이 문서에 기록해야 한다. 확인되지 않은 자산은 사용할 수 없다.

아래는 #1441(공용 3D 선박 asset과 LOD 기준)을 위해 2026-10-14에 저장소 `37c8fc8b` 기준으로 확인한 사실이다. 이 문서는 값을 새로 정하지 않고 지금 코드와 자산이 가진 값을 적으며, 정해지지 않은 것은 마지막 절의 「미정」에 모았다. 이 이슈는 문서 작업이며 코드 동작을 바꾸지 않는다.

## 1. 가장 먼저 밝힐 사실 — 저장소에는 선박 GLB가 없다

선박 GLB·GLTF 파일은 저장소에 한 개도 없고, 과거에 있었던 흔적도 없다. 다음 세 가지로 확인했다.

- `git ls-files`에서 확장자 `.glb`·`.gltf`가 0건이다.
- `git log --all --diff-filter=AD --name-only`에서 `.glb`·`.gltf`가 추가되거나 삭제된 이력이 0건이다.
- 작업 트리를 `find`로 훑어도(`node_modules` 제외) 같은 확장자가 0건이다.

따라서 GLB의 정점·삼각형·텍스처·bounding box 같은 파일 실측은 **할 대상이 없다.** `docs/ADR_3D_MAP_RENDERING.md`도 같은 사실을 적고 있다(맥락 절의 「출처와 재배포 허가를 확인할 수 있는 선박 GLB가 없다」). GLB 로더는 코드에 없다. `GLTFLoader`·`glb`로 `frontend/src`를 찾으면 오류 분류 문자열(`mapFailure.ts`)과 주석·테스트만 나온다.

이슈 완료 기준의 첫째(「라이선스와 출처가 저장소에서 확인된다」)는 GLB 자산이 아니라 **절차형 geometry**에 대해서만 채울 수 있다. 어느 외부 GLB를 쓸지는 저장소의 사실로 정해지지 않으며 「미정」이다.

## 2. 저장소에 있는 선박 표현 자산

| 표현 | 위치 | 크기 | 출처·라이선스 (저장소에서 확인되는 범위) |
|---|---|---|---|
| 지도 위 3D 선박(절차형) | `vesselParts.ts`(135줄) · `vesselLayer.ts`(341줄) · `vesselGeometry.ts`(97줄). 파일로 된 asset은 없다 | asset 0 B, texture 0 B (`vesselModel.ts:23-38`의 `VESSEL_GEOMETRY_BUDGET`) | 저장소가 소유한 코드. `vesselParts.ts` 머리 주석이 형상을 항만 미니어처 실험(`miniature3d/main.ts`)에서 되살렸다고 적는다. 그 실험 파일은 `#1907`이 지웠고 지금 저장소에 없다. 실험 형상의 원저작이 누구인지는 저장소에서 확인되지 않음 |
| 항만 장면의 선박(절차형) | `harborSceneRenderer.ts:128-132` — `BoxGeometry(12, 4, 38)` 하나 | asset 0 B | 저장소가 소유한 코드. 지도 위 선박과 **다른 형상**이다(5절) |
| 지도 마커의 평면 선박(SVG path) | `components/vesselShape.ts:19-26` — path 3개(선체·선실·연돌), 24×24 그리드 | 파일 없음, 코드 안의 문자열 | 저장소가 소유한 코드. 외부 출처 표기는 저장소에서 확인되지 않음 |
| 선종별 선박 일러스트(SVG, 측면) | `components/ShipIllustration.tsx`(205줄) — 7계열 | 파일 없음 | 주석이 「선종마다 측면 실루엣을 직접 그렸다」고 적는다(10/7 디자인 결정). 지도에는 쓰이지 않고 선박 상세·선박 관리 화면이 쓴다 |
| `frontend/public/brand/beomi/*.svg` 3개 | 2,279 B · 2,350 B · 2,414 B | 합계 7,043 B | 캐릭터 그림이며 **선박이 아니다.** 이 문서의 대상이 아니다 |

`frontend/public/` 아래에는 이 밖에 선박 GLB·SVG가 없다(`git ls-files frontend/public`을 `glb|gltf|svg|vessel|ship`으로 걸러 확인했다).

라이선스에 대해 확인되는 것은 한 가지다. 위 절차형 코드에는 제3자 자료가 들어 있지 않다. 다만 이 코드가 의존하는 라이브러리 `three`(`frontend/package.json`의 `^0.186.0`)와 `maplibre-gl`(`^6.11.2`)의 라이선스 고지는 루트 `NOTICE`에서 찾을 수 없다(`NOTICE`에서 `three`·`maplibre`로 찾으면 0건). 이것은 선박 asset이 아니라 라이브러리 고지의 문제이므로 여기서 판단하지 않고 「미정」에 남긴다.

## 3. 절차형 geometry의 실측

### 3.1 구성과 삼각형 수

`vesselParts(mode)`(`vesselParts.ts:63-116`)가 부품 목록을 돌려주고, `vesselLayer.ts:112-127`의 `shapeFor`가 three 기본 도형으로 만든다. 선체는 8각 기둥(`CylinderGeometry`, 위·아래 반지름 비 1 : 0.72, 반지름 분할 8, 높이 분할 1)이고 나머지는 모두 상자다.

삼각형 수는 three 0.186.0을 직접 불러 센 값이다(스크래치 스크립트 `scratchpad/tri.mjs` · `bbox.mjs`).

| 도형 | 삼각형 수(실측) | `vesselTriangleCount`가 쓰는 값(`vesselParts.ts:120`) |
|---|---:|---:|
| `BoxGeometry` | 12 | 12 |
| `CylinderGeometry(…, 8, 1)` | 32 | 32 |
| wake `ConeGeometry(1, 2, 3, 1, true)` | 3 | 세지 않음 |

| 모드 | 부품 수 | 삼각형(실측) | 코드가 세는 값 | 예산(`vesselModel.ts:37`) |
|---|---:|---:|---:|---:|
| `fleet` | 21 (선체 1 · 갑판 1 · 선교 1 · 화물 18) | 272 | 272 | 300 |
| `comparison` · `playback` | 22 (연돌 1 추가) | 284 | 284 | 320 |

실측과 코드의 계산이 같다. #1441에서 처음 쟀을 때는 코드가 기둥을 28로 세어(뚜껑을 12로 셈) 4만큼 달랐고, #2454에서 식을 32로 바로잡았다. three의 뚜껑은 반지름 분할 수(8)만큼의 삼각형을 위와 아래에 하나씩 두므로 16이다. `vesselParts.test.ts`가 계산값을 three로 실제 만든 geometry의 삼각형 수와 견준다.

부품은 모두 별도 `Mesh`다. 배 한 척이 fleet에서 21개, 추적에서 22개의 mesh이고 인스턴싱은 없다. 도형은 크기별로(`vesselLayer.ts:114`), 재질은 등급 토큰별로 배 사이에 나눠 쓴다(`vesselLayer.ts:64-109`). 화면에 척수 상한을 두는 코드는 지도에 없다(지도 쪽 코드에서 상한 상수를 찾지 못했다).

### 3.2 좌표계 · 단위 · 원점 · forward axis · bounding box

부품 데이터의 약속은 `vesselParts.ts:22`에 있다. 단위는 **선체 길이 = 1**, 위가 `+Y`, 앞(선수)이 `+Z`다. 원점은 `vesselParts.ts:40`의 주석대로 흘수선 중앙이다.

fleet 모드의 부품을 위 식 그대로 조립해 잰 bounding box는 다음과 같다(길이 1 단위).

| 모드 | x (폭) | y (높이) | z (길이) |
|---|---|---|---|
| fleet | -0.15 ~ 0.15 | -0.07 ~ 0.28 | -0.5 ~ 0.5 |
| comparison · playback | -0.15 ~ 0.15 | -0.07 ~ 0.38 | -0.5 ~ 0.5 |

길이가 1이고 폭이 0.3이므로 긴 축은 `z`다. 선수가 `+Z`라는 판단의 근거는 둘이다. 하나는 선교(`z = -0.34`)와 연돌(`z = -0.36`)이 `-Z` 쪽에 서 있다는 점이다. 다른 하나는 렌더러가 부품 묶음을 `X`축으로 90° 눕히는 회전(`vesselLayer.ts:147`)인데, 이 회전은 `+Z`를 화면 위쪽(`-Y`)으로 보낸다. 이 두 번째 근거는 회전 행렬을 직접 풀어 얻은 해석이고 화면에서 눈으로 확인한 것은 아니다(정황).

`VESSEL_GEOMETRY_BUDGET`(`vesselModel.ts`)의 `forwardAxis`·`unit`도 같은 약속을 적는다(`'+Z'` · `'hull-length'`). #1441 때는 `'+Y'` · `'meter'`로 적혀 부품 명세와 달랐고 #2454에서 맞췄다. 이 상수를 읽어 동작이 달라지는 코드는 없다.

**확인되지 않은 것이 하나 있다.**

- 선체는 선수(`+Z`) 쪽의 반폭이 0.150이고 선미(`-Z`) 쪽이 0.108이다. 선수 쪽이 넓고 선미 쪽이 좁다. `vesselParts.ts:66`의 주석은 「위가 넓고 아래가 좁아」라고 적는다. 옆면이 꺾여 보이게 하려는 의도는 읽히지만, 기둥을 눕힌 뒤의 넓은 쪽은 위가 아니라 선수다. 이것이 의도인지는 저장소에서 확인되지 않으며 디자인 판단이라 「미정」에 둔다.

### 3.3 텍스처

텍스처는 0개다. 색은 CSS 토큰(`--cii-{a-e}-fill`, `--surface-card`, `--surface-inset`, `--surface-page`, `--color-border-control`)을 `getComputedStyle`로 읽어 재질 색으로 넣는다(`vesselLayer.ts:67-80`). 토큰을 읽을 수 없는 환경에서는 코드 안의 기본 색으로 떨어진다. 등급이 없으면 중립색이다.

## 4. 렌더러가 적용하는 보정

공용 layer는 `createGlobeVesselLayer`(`vesselLayer.ts:47`) 하나이고, 선대 지도와 단일 추적이 같은 함수를 쓴다. 지도 위에 자기 캔버스를 한 장 얹고(`vesselLayer.ts:264-266`, 288) `map.project()`가 준 화면 좌표에 그린다. 캔버스는 포인터를 받지 않는다(`FleetMap.css:233-239`).

| 보정 | 값 | 위치 |
|---|---|---|
| 카메라 | `OrthographicCamera(0, 1, 0, 1, -1000, 1000)`, 매 프레임 지도 캔버스 크기로 갱신 | `vesselLayer.ts:290`, `191-197` |
| 크기 | 화면에서 **44 px**를 유지한다. 축척이 아니라 기호다. `mesh.scale = 44 × (캔버스 폭 / clientWidth)` | `vesselGeometry.ts:164`, `vesselLayer.ts:225`, `248` |
| 눕히기 | 부품 묶음을 `X`축으로 90° 회전 | `vesselLayer.ts:147` |
| 기둥 눕히기 | 선체 기둥 도형에 `rotateX(π/2)`, 그리고 `scale(1, 높이/폭, 1)` | `vesselLayer.ts:121-124` |
| 방위 | `(heading ?? 0) + 지도 bearing`를 `rotation.z = -facing`으로 적용. heading이 없으면 북쪽을 향한다 | `vesselLayer.ts:246`, `250` |
| 기울기 | 지도 pitch를 `rotation.x`로 그대로 받는다 | `vesselLayer.ts:224`, `250` |
| 자리 | `mesh.position = (x, y, 0)`, x·y는 `map.project()` 결과 × 픽셀 비율 | `vesselLayer.ts:238-247` |
| 조명 | `HemisphereLight` 강도 2.4 + `DirectionalLight` 강도 1.7 | `vesselLayer.ts:292-296` |
| 지구 뒷면 | `transform.isLocationOccluded`, 없으면 중심 각거리 82° 초과 | `vesselLayer.ts:211-223`, `vesselGeometry.ts:218-232` |
| 항적 wake | 속도 있음·재생 중·움직임 허용일 때만. 길이 배수 `min(2.2, 1 + 노트/20)` | `vesselModel.ts:44-48`, `vesselLayer.ts:256-259` |

`vesselParts.ts`가 선수를 `+Z`로 미리 맞춰 두었으므로 호출부는 방위만 더한다. 이것이 이슈 완료 기준의 둘째(「공용 renderer가 별도 보정 없이 방향·크기를 적용할 수 있다」)에 대한 현재 상태이다. 절차형 geometry에서는 방향과 크기가 코드 안의 약속으로 이미 맞춰져 있다. **외부 GLB에 대해서는 판단할 수 없다.** GLB가 없으므로 그 파일의 원점·축·단위를 지금 코드에 맞춰야 하는지는 확인할 대상 자체가 없다.

## 5. 화면별 사용

| 화면(코드) | 3D 선박 | 모델 | 비고 |
|---|---|---|---|
| 선대 지도(`mapLibreRenderer.ts:363-378`, `FleetMap.tsx:381-388`) | 지구본 투영이고 선박이 1척 이상일 때만 `vesselLayer`를 올린다(`:368`) | `vesselParts('fleet')` — 연돌 없음, 21 mesh | heading은 서버 `courseDeg`, 등급은 `ytdRating`으로 선체 색을 정한다 |
| 항로 비교(`comparison`) | 입력은 받지만 선박 위치 정본이 없어 선박을 추가하지 않는다(ADR의 서술. 코드는 `mode`를 그대로 넘긴다) | `vesselParts('comparison')` — 연돌 있음 | 위 서술은 ADR 기준이며 이 이슈에서 코드로 재확인하지 않았다 |
| 연간 재생(`playbackRenderer.ts:149-158`, `182-190`) | `quality.globe`일 때만, 선박 1척(`id: 'playback-vessel'`) | `vesselParts('playback')` — 연돌 있음, 22 mesh | heading은 `activeRouteBearing`, 등급은 넘기지 않아 중립색. 평면 `◆` DOM 마커가 함께 있다(`:145-149`) |
| 항만 장면(`harborSceneRenderer.ts:128-132`) | 별도 three 장면 | `BoxGeometry(12, 4, 38)` 상자 1개, 방위·등급 없음 | 지도 위 선박과 **같은 모델이 아니다.** 단위는 장면 미터로 보이나 실제 선박 크기 근거는 저장소에서 확인되지 않음 |

선대 지도와 단일 추적은 같은 부품 데이터를 쓰되 연돌 1개 차이로만 갈린다. 「다중 선박용」과 「단일 추적용」으로 따로 만든 단순화 모델은 없다. 이슈 체크리스트의 「Fleet 다중 선박과 단일 추적용 LOD 정의」는 이 연돌 유무와 아래 성능 단계로만 존재한다.

## 6. LOD · 성능 수치 — 지금 코드가 쓰는 값

**정해진 LOD 수치는 코드에 한 벌만 있다.** 새 기준(예: 모바일 삼각형 상한)은 저장소 어디에도 없고, 이 문서도 지어내지 않는다.

| 항목 | 값 | 출처 |
|---|---|---|
| 삼각형 예산 — fleet / 추적 | 300 / 320 (실측 272 / 284) | `vesselModel.ts:37`, 3.1 |
| texture · asset 파일 | 0 B · 0 B | `vesselModel.ts:37` |
| 테스트가 잠그는 상한 | fleet 400 이하, 추적 500 이하 | `vesselModel.test.ts` |
| 동시 표시 선박 수 상한 | **정해진 수치가 없다.** 지금은 위치를 가진 모든 선박이 한 척당 21 mesh로 그려진다 | `vesselLayer.ts:161-179` |
| 화면 선박 크기 | 44 px | `vesselGeometry.ts:164` |
| 3D 선박 layer 번들 | 예산 10 KiB 이하(`check-map-performance.mjs`) | `PERFORMANCE.md`의 표는 1,828 B로 적혀 있으나 layer가 커진 뒤 갱신되지 않았을 수 있다(정황 — 측정은 이 이슈에서 하지 않았다) |
| frame 예산 | desktop p95 16.7 ms 이하, mobile p95 33.3 ms 이하 | `PERFORMANCE.md`. 측정값은 「브라우저 QA에서 측정」으로만 적혀 있다 |

성능 단계(`quality.ts:26-42`)가 3D 선박에 미치는 영향이다.

| 단계 | 판정 조건 | 3D 선박 | pixel ratio 상한 | 항만 건물 | animation |
|---|---|---|---:|---|---|
| low | reduced-motion, 메모리 4 GB 이하, 코어 4 이하, WebGL2 없음 중 하나 | **없다.** `globe: false`라 평면으로 가고 SVG 마커만 남는다 | 1 | 4개 중 1개 | 없음 |
| medium | low도 high도 아님 | 있다 | 1.5 | 2개 중 1개 | reduced-motion이 아닐 때 |
| high | 메모리 8 GB 이상, 코어 8 이상, 최대 텍스처 8192 이상 | 있다 | 2 | 전체 | reduced-motion이 아닐 때 |

3D 선박은 **켜짐과 꺼짐 두 상태뿐이다.** medium과 high에서 선박 부품 수나 삼각형 수는 같다. pixel ratio 상한은 항만 장면에만 적용된다(`harborSceneRenderer.ts:102`). 선박 layer는 `devicePixelRatio`를 그대로 쓴다(`vesselLayer.ts:273`). wake는 `quality.animate`가 거짓이거나 `reducedMotion`이면 꺼진다(`playbackRenderer.ts:187`).

## 7. SVG 폴백과 3D 모델은 같은 것을 뜻하는가

3D가 꺼지면(low 단계, 평면 투영, WebGL 실패) 지도에는 DOM 마커의 SVG 배가 남는다(`FleetMap.tsx:173-215`, 22 px — `FleetMap.css:131-133`). 3D가 켜지면 같은 자리에 배가 둘이 되지 않도록 SVG를 숨기고 등급 배지만 남긴다(`FleetMap.css:217-223`).

| 항목 | 3D 모델 | SVG 마커 | 일치 |
|---|---|---|---|
| 방향 | 서버 `courseDeg`, 없으면 북쪽을 향한다(`vesselLayer.ts:246`) | 서버 `courseDeg`만큼 `rotate`, 없으면 돌리지 않는다(`FleetMap.tsx:206-209`) | **다르다.** 값이 없을 때 3D는 북향으로 그리고 SVG는 방향을 그리지 않는다. 정본(`DESIGN_SYSTEM §9.5`)은 「값이 없으면 돌리지 않는다, 없는 방향을 0°로 그리지 않는다」이다 |
| 선종 | 선종 구분 없음. `vesselParts(mode)`는 선종을 받지 않는다 | 선종 구분 없음. path 3개 한 벌 | 같다 |
| 크기 | 44 px | 22 px | 다르다. 크기는 둘 다 축척이 아니라 기호다 |
| 등급 | 선체·갑판 색(`--cii-*-fill`), 문자는 마커 배지 | path 채움(`--cii-*-fill`), 문자는 배지 | 같다. 3D에서 문자 채널은 배지가 계속 맡는다 |
| 형상 | 위에서 본 선체 + 갑판 + 선교 + 화물, 선교가 선미 쪽 | 측면 실루엣(선체 사다리꼴 + 선실 + 연돌) | **같은 그림이 아니다.** 선수가 어느 쪽인지의 표현이 다르다 |
| 정박 · 묘박 | 별도 표현 없음 | 닻 배지 `⚓`(`FleetMap.tsx:222-229`) | 3D에는 정박 표시가 없다 |

SVG의 path 3개는 좌우로 비대칭이지만 측면 그림이라 선수가 어디인지를 path만으로는 말하지 않는다. `rotate(course)`가 아이콘의 위쪽을 진행 방향에 맞추는 것으로 읽히나, 위쪽이 선수를 뜻하는지는 코드에서 확인되지 않는다(정황). 이슈의 「SVG fallback asset과 의미 일치 확인」은 방향·선종·등급·크기의 표로 확인했고, **방향의 결측 처리와 형상 표현은 일치하지 않는다.** 어느 쪽을 맞출지는 디자인 담당 소관(`AGENTS §3.2.2`)이라 「미정」에 둔다.

## 8. 이슈 항목별 상태

| 이슈 항목 | 상태 |
|---|---|
| 선박 GLB asset과 재배포 라이선스 확인 | GLB가 저장소에 없다(1절). 절차형 geometry의 출처는 저장소 소유로 확인된다. **외부 GLB의 선정·라이선스 확인은 저장소의 사실로 채울 수 없다** |
| 좌표계·forward axis·단위·원점 규칙 | 절차형 geometry에 대해 3.2에 실측으로 적었다. `VESSEL_GEOMETRY_BUDGET`의 `forwardAxis`·`unit`도 같은 값이다(#2454) |
| polygon·texture·파일 크기 budget 측정 | 삼각형 272 / 284, texture 0, asset 0 B를 실측했다. 번들 크기는 `PERFORMANCE.md`가 단일 기록 위치이고 이번에 다시 재지 않았다 |
| Fleet 다중 선박과 단일 추적용 LOD | 현재 값을 5·6절에 표로 정리했다. 척수 상한·모바일 기준 같은 **새 수치는 정해진 적이 없다** |
| SVG fallback과 의미 일치 | 7절에서 대조했다. 일치하지 않는 두 곳이 있다 |

## 9. 미정 — 정해야 하나 저장소의 사실로는 정할 수 없는 것

- 외부 GLB를 쓸 것인가. 쓴다면 선정, 출처, 재배포 라이선스 원문. 쓰지 않는다면 절차형 geometry를 최종으로 확정하고 이 이슈의 GLB 항목을 닫을지.
- 동시 표시 선박 수 상한. 지금은 상한이 없다.
- 모바일·저사양용 삼각형 또는 mesh 수 기준. 지금 low 단계는 3D를 아예 끄고, medium과 high는 같은 모델을 쓴다.
- 예산 300·320과 테스트 상한 400·500의 관계를 정리할지.
- 선체 기둥이 선수 쪽이 넓은 것이 의도인지(디자인).
- heading이 없을 때 3D 선박을 북향으로 그리는 현재 동작이 `DESIGN_SYSTEM §9.5`와 맞는지(디자인).
- 3D 선박에 정박·묘박 표시를 둘지(디자인).
- `three`·`maplibre-gl`의 라이선스 고지를 `NOTICE`에 둘지.
- `docs/ADR_3D_MAP_RENDERING.md`의 「결정」 절은 MapLibre의 WebGL context와 matrix를 공유하는 custom layer라고 적는데, 코드는 별도 overlay 캔버스에 그린다. 같은 문서의 「선박 geometry·LOD 계약」 절(geometry 형상 · 선수 축 · 단위 · 삼각형 상한)은 #2454에서 현행 코드에 맞췄다.
