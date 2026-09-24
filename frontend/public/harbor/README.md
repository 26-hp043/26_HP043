# 부산·싱가포르 항만 3D 실험용 OSM 스냅샷

`busan-north-port.json`은 2026-09-24 12:30:10 UTC에 [OpenStreetMap API 0.6 지도 조회](https://api.openstreetmap.org/api/0.6/map?bbox=129.035,35.105,129.055,35.120)로 받은 데이터를 변환한 파생 데이터베이스다. 범위는 `[서쪽 경도 129.035, 남쪽 위도 35.105, 동쪽 경도 129.055, 북쪽 위도 35.120]`이다. 런타임에서는 네트워크 요청 없이 이 JSON만 읽는다.

`singapore-harbor.json`은 2026-09-24 14:14:03 UTC에 [OSM API 0.6의 탄종파가 항만 구역](https://api.openstreetmap.org/api/0.6/map?bbox=103.827,1.252,103.851,1.274)을 조회해 같은 규칙으로 변환했다. 범위는 `[103.827, 1.252, 103.851, 1.274]`이고 건물 202개, 도로 선분 1,111개, 해안선 선분 6개를 담는다. 앞선 예시 해상 경로의 도착점 `(103.85, 1.2833)`은 이 bbox 북쪽 경계에서 약 1 km 떨어져 있다. 따라서 3D 장면을 실제 항로의 정확한 종착점이나 접안 위치로 제시해서는 안 된다. 도착점 주변 마리나베이 구역 `[103.842, 1.275, 103.867, 1.294]`의 OSM API 응답에는 `natural=coastline` way가 없어서, 해안선이 있는 실제 항만 구역을 별도 선택했다. 두 JSON 모두 런타임에서 네트워크 요청 없이 읽는다.

## 변환 규칙과 한계

- 닫힌 `building` way 중 footprint가 범위 안에 전부 들어오는 것만 보존한다. 건물 relation과 경계에 걸친 건물은 포함하지 않는다.
- `heightMeters`의 출처를 `heightSource`에 적는다. `height` 태그는 측정값이라고 보증하지 않으며 OSM에 기록된 값 그대로 사용한다. `building:levels`는 층당 3m로 환산한 **추정치**다. 두 태그가 없으면 way ID에서 결정적으로 만든 6–18m **시각화용 임의 높이**를 사용한다. `fallback:estimated`를 실제 건물 높이로 해석하면 안 된다.
- `highway`와 `natural=coastline` way는 방향을 유지한 선분으로 변환하고 경계에서 자른다. OSM API는 범위 밖의 way 참조 노드도 응답에 포함한다.
- 두 구역의 해안선은 범위를 나갔다 다시 들어오는 열린 선분이다. 해안선과 bbox만으로 항만의 육지·수면 면을 신뢰성 있게 확정할 수 없어 `waterPolygons` 또는 `landPolygons`는 제공하지 않는다. 렌더러가 해안선을 임의로 이어 닫거나 수면을 실측 지형처럼 표시해서는 안 된다.
- OSM 데이터의 누락·갱신과 단순화된 건물 높이 때문에 실제 항해·측량·규제 판단에는 사용할 수 없다.

## 재생성

별도로 보관한 원본 OSM XML을 사용하면 같은 내용의 JSON을 재생성할 수 있다. 원본 XML은 이 저장소에 포함하지 않는다. `metadata.sourceSha256`으로 XML이 생성 당시 입력과 같은지 확인한다.

```sh
python3 frontend/scripts/build-harbor-snapshot.py \
  --input /path/to/busan-north-port.osm \
  --retrieved-at 2026-09-24T12:30:10Z

python3 frontend/scripts/build-harbor-snapshot.py \
  --harbor singapore \
  --input /path/to/singapore-harbor.osm \
  --retrieved-at 2026-09-24T14:14:03Z
```

`--harbor` 기본값은 `busan`이다. `--input` 없이 실행하면 선택한 bbox의 **현재** OSM 데이터를 새로 받아 스냅샷을 갱신한다. 그 경우 데이터 내용과 `retrievedAt`이 바뀔 수 있다. 생성 당시 싱가포르 원본 XML의 SHA-256은 `7b5c0ff3d4f19701af820c0d69b1b63717d72db8511589bbd634ebfb0ccd2cd7`이다.

## 저작자 표시·라이선스

© OpenStreetMap contributors. 원천 데이터와 두 JSON 파생 데이터베이스는 [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/)에 따른다. 지도 화면에 `© OpenStreetMap contributors`와 [OpenStreetMap 저작권 안내](https://www.openstreetmap.org/copyright) 링크를 표시해야 한다. 파생 데이터베이스는 이 저장소의 `frontend/public/harbor/busan-north-port.json` 및 `frontend/public/harbor/singapore-harbor.json`으로 제공하며, 재생성·검증 코드는 `frontend/scripts/build-harbor-snapshot.py`로 제공한다. 이 데이터를 재배포하거나 이를 기반으로 공개용 파생 데이터베이스를 만들 때 ODbL의 저작자 표시, 동일조건 공유 및 파생 데이터베이스 제공 의무를 확인해야 한다.

## 부산→싱가포르 표시용 해상 경로

`busan-singapore-searoute.json`은 3D 항로 조망 실험에서만 쓰는 오프라인 좌표다. 출발점 `(129.0333, 35.1)`과 도착점 `(103.85, 1.2833)`을 [searoute-py가 배포하는 Eurostat SeaRoute `marnet_searoute.geojson`](https://github.com/genthalili/searoute-py/blob/main/searoute/data/marnet_searoute.geojson)의 그래프에 붙이고, `build-route-fixture.py`가 각 선분의 대권거리를 가중치로 독립 Dijkstra 탐색했다. 라이브러리의 기본 제한과 같이 북서항로(`northwest`) 선분을 제외했다. **프로젝트의 SeaRoute 서비스가 생성한 결과라고 주장하지 않는다.** 사용한 원본의 Git blob SHA와 SHA-256은 JSON 메타데이터에 있으며, 스크립트는 Git blob SHA가 달라지면 중단한다.

```sh
python3 frontend/scripts/build-route-fixture.py
# 또는 원본을 별도로 내려받은 경우
python3 frontend/scripts/build-route-fixture.py --network-file /path/to/marnet_searoute.geojson
```

경로망에서 연결된 길이 없으면 직선으로 대체하지 않고 실패한다. 양끝의 지정 좌표와 최근접 경로망 노드 사이에는 접속 선분이 있으므로 **항만 진입 가능성이나 육지·수심 안전성을 보증하지 않는다.** 실제 항해 계획이 아니며 연간 시뮬레이션의 항차나 CII 계산 거리에 사용하지 않는다.

경로망 데이터: © Eurostat SeaRoute, [EUPL-1.2](https://joinup.ec.europa.eu/collection/eupl/eupl-text-eupl-12). 배포 도구: [searoute-py](https://github.com/genthalili/searoute-py), Apache-2.0. 3D 실험 화면에도 이 출처를 표시해야 한다.
