# 연간 시뮬레이션 시각화 경계

`AnnualSimulationResult`가 계산 결과의 정본이다(`API_SPEC §6.1`, `TECH_SPEC §11`).
이 폴더의 `model.ts`는 그 결과를 렌더러가 읽을 형태로 옮긴다. CII,
Monte Carlo 확률, 등급, 감축량은 시각화 계층에서 다시 계산하지 않는다.
`AnnualSimulation.tsx`는 결과를 전달하고 장면의 표시 여부만 정한다.

## 데이터 흐름

1. `AnnualSimulationProvider`가 서버의 저장된 실행 결과를 받는다.
2. `createVisualizationModel`이 필요한 수치 문자열과 등급을 그대로 복사한다.
3. 별도 지리 데이터 공급자가 **같은 `snapshot_id`** 에 속하는 좌표를 제공한 경우에만
   `MapGeometry.available`을 전달한다. 스냅샷 ID가 다르면 모델 생성이 실패한다.
4. 렌더러는 모델을 그리며 `mount`·`update`·`destroy` 계약으로 수명 주기를 관리한다.

현재 `API_SPEC §6.1`·`§6.3`의 결과와 스냅샷 항차에는 좌표가 없다. 따라서 기본
모델은 `coordinates_not_provided` 상태다. 거리·속력·항차 순서에서 위경도나 실제
항로를 추정하지 않는다. 위치 재생을 붙이려면 스냅샷에 결부된 좌표의 출처와
조회 계약을 먼저 정의해야 한다. 지도 선의 길이도 CII 계산 거리로 되돌려 쓰지 않는다.

## 구현 교체

`MapCoordinate`는 `[경도, 위도]`로 표현한다. 카메라 각도, 지도 타일, 마커,
애니메이션 프레임, WebGL 자원은 모델에 담지 않고 렌더러가 소유한다. MapLibre
2.5D, Three, full 3D 구현을 바꿀 때 계산 응답·모델 필드는 유지하고
`AnnualSimulationRenderer` 구현만 교체한다. 실험 코드는 `experiments/`에 격리한다.

렌더러는 등급을 표시할 때 `DESIGN_SYSTEM §14`의 문자 또는 패턴 병행 규칙을
따르고, 수치 문자열을 임의의 `number`로 변환해 판정에 사용하지 않는다.
