"""Eurostat SeaRoute 해상 경로망에서 부산→싱가포르 표시용 경로를 생성한다.

`searoute-py`가 배포하는 marnet GeoJSON을 읽고 동일한 기본 통과 제한
(northwest)을 적용한다. 그래프에 경로가 없으면 직선을 만들지 않고 실패한다.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen


OUTPUT = Path(__file__).resolve().parents[1] / "public/harbor/busan-singapore-searoute.json"
NETWORK_URL = (
    "https://raw.githubusercontent.com/genthalili/searoute-py/main/"
    "searoute/data/marnet_searoute.geojson"
)
NETWORK_GIT_BLOB = "a9edbd2e17d8426371b78af42ed767fb509203d7"
BUSAN = (129.0333, 35.1)
SINGAPORE = (103.85, 1.2833)


def distance_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 경위도 점의 대권거리(해리) — 경로 탐색 가중치와 표시 길이."""
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = math.radians(b[0] - a[0])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))


def load_network(path: Path | None) -> tuple[dict, str]:
    raw = path.read_bytes() if path else urlopen(NETWORK_URL, timeout=30).read()
    blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if blob_sha != NETWORK_GIT_BLOB:
        raise ValueError(f"SeaRoute 경로망 버전이 바뀌었다: {blob_sha}")
    network = json.loads(raw)
    if network.get("type") != "FeatureCollection" or not network.get("features"):
        raise ValueError("SeaRoute 해상 경로망 형식이 올바르지 않다.")
    return network, hashlib.sha256(raw).hexdigest()


def build_graph(network: dict) -> dict[tuple[float, float], list[tuple[float, tuple[float, float]]]]:
    graph: dict[tuple[float, float], list[tuple[float, tuple[float, float]]]] = defaultdict(list)
    for feature in network["features"]:
        if feature.get("properties", {}).get("passage") == "northwest":
            continue
        geometry = feature["geometry"]
        if geometry["type"] == "LineString":
            segments = [geometry["coordinates"]]
        elif geometry["type"] == "MultiLineString":
            segments = geometry["coordinates"]
        else:
            continue
        for segment in segments:
            for raw_a, raw_b in zip(segment, segment[1:]):
                a, b = tuple(raw_a), tuple(raw_b)
                weight = distance_nm(a, b)
                graph[a].append((weight, b))
                graph[b].append((weight, a))
    return graph


def closest_node(point: tuple[float, float], graph: dict) -> tuple[float, float]:
    return min(graph, key=lambda candidate: distance_nm(point, candidate))


def shortest_path(graph: dict, origin: tuple[float, float], destination: tuple[float, float]) -> list:
    start, finish = closest_node(origin, graph), closest_node(destination, graph)
    queue = [(0.0, start)]
    distances = {start: 0.0}
    previous = {}
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > distances[node]:
            continue
        if node == finish:
            break
        for weight, neighbor in graph[node]:
            next_cost = cost + weight
            if next_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = next_cost
                previous[neighbor] = node
                heapq.heappush(queue, (next_cost, neighbor))
    if finish not in distances:
        raise ValueError("해상 경로망에서 부산과 싱가포르를 잇는 경로가 없다.")
    path = [finish]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    if len(path) < 2:
        raise ValueError("경로망 중간 지점이 없어 스냅샷을 만들지 않는다.")
    return [origin, *path, destination]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-file", type=Path, help="다운로드한 marnet_searoute.geojson")
    args = parser.parse_args()
    network, source_sha = load_network(args.network_file)
    graph = build_graph(network)
    path = shortest_path(graph, BUSAN, SINGAPORE)
    length_nm = sum(distance_nm(a, b) for a, b in zip(path, path[1:]))
    result = {
        "metadata": {
            "source": "Eurostat SeaRoute / searoute-py marnet network",
            "sourceUrl": NETWORK_URL,
            "sourceGitBlob": NETWORK_GIT_BLOB,
            "sourceSha256": source_sha,
            "generator": "frontend/scripts/build-route-fixture.py (Dijkstra; northwest passage excluded)",
            "license": "Eurostat SeaRoute: EUPL-1.2; searoute-py: Apache-2.0",
            "attribution": "해상 경로망 © Eurostat SeaRoute (EUPL-1.2) · searoute (Apache-2.0)",
            "description": (
                "부산→싱가포르 3D 표시 실험용 해상 경로망 최단 경로. "
                "연간 시뮬레이션 항차나 실제 항해 계획이 아니며 CII 계산 거리에 사용하지 않는다."
            ),
            "origin": {"name": "부산", "coordinates": list(BUSAN)},
            "destination": {"name": "싱가포르", "coordinates": list(SINGAPORE)},
        },
        "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in path],
        "lengthNm": round(length_nm, 2),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{OUTPUT}: {len(path)}점, {length_nm:.2f} NM")


if __name__ == "__main__":
    main()
