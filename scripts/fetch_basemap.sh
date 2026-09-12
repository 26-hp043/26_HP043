#!/usr/bin/env bash
#
# 지도 자산을 내려받는다 (#763).
#
# ## 저장소에 넣지 않는 이유
#
# 타일 83 MB + 글리프 12 MB = **95 MB**다(2026-09-12 실측). 이미지가 이미 699 MB라
# 여기에 더할 수 없고, git에 넣으면 clone 한 번에 그만큼이 따라온다.
#
# ## 자산이 없어도 화면은 뜬다
#
# `FleetDashboard`가 `HEAD` 한 번으로 있는지 묻고, 없으면 **개략도**(`PositionChart`)로
# 떨어진다. 그래서 이 스크립트는 **배포의 선행 조건이 아니라 선택**이다.
#
# ## 무엇을 담나 (`#763` ⓐ 결정)
#
#   전 세계 z0–z6      44.9 MB  — 해역과 국가가 읽힌다
#   항만 43곳 z7–z10   38.0 MB  — 항만 구역과 방파제 안쪽이 읽힌다
#   글리프 2종 × 256   12.0 MB  — 라벨. CDN을 쓰지 않는다(오프라인)
#
# 항로(대양)에는 깊은 층을 주지 않는다 — 확대해도 새로 보일 것이 없다. z10을 상한으로
# 둔 것은 **위치 데이터가 그 이상의 정확도를 받치지 못하기** 때문이다(사람이 찍은 한 점).
#
# ## 쓰는 법
#
#   scripts/fetch_basemap.sh [출력 디렉터리]
#
# 기본 출력은 `./basemap`이다. nginx가 `/basemap/`으로 서빙하고 **Range 요청을
# 지원**해야 한다(PMTiles가 파일 일부만 읽는다).
set -euo pipefail

OUT="${1:-./basemap}"
BUILD_DATE="${BASEMAP_BUILD_DATE:-20260912}"
PLANET="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
FONT_CDN="https://cdn.protomaps.com/fonts/pbf"

# 항만 상자의 반변(도). 0.25°는 약 55 km — 항만과 접근 수로가 함께 든다.
BOX="${BASEMAP_PORT_BOX:-0.25}"

command -v pmtiles >/dev/null 2>&1 || {
  echo "pmtiles CLI가 필요합니다 — https://github.com/protomaps/go-pmtiles/releases" >&2
  exit 1
}

mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[1/4] 항만 상자 GeoJSON 생성 (반변 ${BOX}°)"
python3 - "$BOX" > "$WORK/ports.geojson" <<'PY'
import json
import sys

sys.path.insert(0, "src")
from cii_platform.services.sample_ports import SAMPLE_PORTS

d = float(sys.argv[1])
rings = []
for port in SAMPLE_PORTS:
    lat, lon = float(port.lat), float(port.lon)
    rings.append(
        [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]]
    )
json.dump(
    {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": rings}, "properties": {}},
    sys.stdout,
)
PY

echo "[2/4] 전 세계 z0–z6 추출"
pmtiles extract "$PLANET" "$WORK/world.pmtiles" --maxzoom=6

echo "[3/4] 항만 주변 z7–z10 추출"
pmtiles extract "$PLANET" "$WORK/ports.pmtiles" \
  --region="$WORK/ports.geojson" --minzoom=7 --maxzoom=10

pmtiles merge "$WORK/world.pmtiles" "$WORK/ports.pmtiles" "$OUT/bluelog.pmtiles"

echo "[4/4] 글리프 — 2종 × 256 range"
for stack in "Noto Sans Regular" "Noto Sans Medium"; do
  dir="$OUT/fonts/$stack"
  mkdir -p "$dir"
  encoded="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$stack")"
  # 빈 range가 많아 실패를 무시한다(`-f` + `|| true`) — 없는 구간은 라벨도 없다.
  seq 0 255 | xargs -P 16 -I{} sh -c \
    'i={}; s=$((i*256)); e=$((s+255)); curl -sf -o "'"$dir"'/$s-$e.pbf" "'"$FONT_CDN/$encoded"'/$s-$e.pbf" || true'
done

echo "완료 — $(du -sh "$OUT" | cut -f1)"
echo "  타일   $OUT/bluelog.pmtiles"
echo "  글리프 $OUT/fonts/"
