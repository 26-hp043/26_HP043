#!/usr/bin/env bash
#
# 지도 자산을 다시 만든다 (#763 · #985).
#
# ## 평소에는 돌릴 일이 없다
#
# 산출물은 **저장소에 들어 있다**(`frontend/public/basemap/`). 이 스크립트는 타일을
# 갱신하거나 담는 범위를 바꿀 때만 돌린다.
#
# ## 무엇을 담나 (`#985` · 2026-09-18 실측)
#
#   전 세계 z0–z5      15 MB  — 해역·국가·주요 도시가 읽힌다
#   글리프 2종 × 256   12 MB  — 라벨. CDN을 쓰지 않는다(오프라인)
#
# **z5가 상한인 것은 배포처 제한 때문이다** — 프론트엔드는 Cloudflare Pages에 올라가고,
# 그쪽은 **파일 하나가 25 MiB**를 넘을 수 없다. z0–z6은 44.9 MB, 항만 43곳 z7–z10을
# 더하면 83 MB라 어느 쪽도 올라가지 않는다.
#
# 잃는 것은 크지 않다. 화면이 실제로 쓰는 축척은 **z3~4**다 — 선대가 대륙에 걸쳐
# 흩어져 있으면 한 화면에 위도 50°대가 들어온다. 그리고 **위치 데이터가 더 깊은 층을
# 받치지 못한다**(사람이 찍은 한 점). AIS(`#764`)가 붙어 관측이 쌓이면 그때 늘린다.
# `MAX_ZOOM`(`basemap.ts`)이 이 상한과 짝이며, 한쪽만 바꾸면 overzoom으로 뭉툭해진다.
#
# ## 자산이 없어도 화면은 뜬다
#
# `FleetDashboard`가 매직 넘버 7바이트로 있는지 묻고(`#1144`), 없으면
# **개략도**(`PositionChart`)로 떨어진다. 다른 사람의 로컬이나 얕은 clone에서도
# 화면이 깨지지 않는다.
#
# ## 쓰는 법
#
#   scripts/fetch_basemap.sh [출력 디렉터리]
#
# 기본 출력은 `frontend/public/basemap`이고 **개발과 배포가 같은 자리를 쓴다.**
#
#   개발  Vite가 `public/`을 오리진 루트로 서빙한다 → `/basemap/...`
#   배포  `npm run build`가 `public/`을 `dist/`로 옮기고 Cloudflare Pages가 그
#         `dist`를 서빙한다 → 같은 `/basemap/...`
#
# 돌린 뒤에는 **산출물을 커밋한다** — 저장소에 없으면 배포본에서 개략도만 뜬다.
#
# 서버는 **Range 요청을 지원**해야 한다(PMTiles가 파일 일부만 읽는다). Vite와
# Cloudflare Pages 모두 지원한다.

set -euo pipefail

OUT="${1:-frontend/public/basemap}"
BUILD_DATE="${BASEMAP_BUILD_DATE:-20260912}"
PLANET="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
FONT_CDN="https://cdn.protomaps.com/fonts/pbf"

# 전 세계 타일의 줌 상한. **올리기 전에 25 MiB를 넘지 않는지 반드시 잰다** — 넘으면
# Cloudflare Pages가 파일을 거부해 배포본에서만 지도가 사라진다(로컬에서는 뜬다).
MAX_ZOOM="${BASEMAP_MAX_ZOOM:-5}"

command -v pmtiles >/dev/null 2>&1 || {
  echo "pmtiles CLI가 필요합니다 — https://github.com/protomaps/go-pmtiles/releases" >&2
  exit 1
}

mkdir -p "$OUT"

echo "[1/2] 전 세계 z0–z${MAX_ZOOM} 추출"
pmtiles extract "$PLANET" "$OUT/bluelog.pmtiles" --maxzoom="$MAX_ZOOM"

SIZE_MIB=$(( $(wc -c < "$OUT/bluelog.pmtiles") / 1048576 ))
if [ "$SIZE_MIB" -ge 25 ]; then
  echo "경고: 타일이 ${SIZE_MIB} MiB로 Cloudflare Pages 상한(25 MiB)을 넘었습니다." >&2
  echo "      BASEMAP_MAX_ZOOM을 낮추거나 배포처를 바꿔야 합니다." >&2
fi

echo "[2/2] 글리프 — 2종 × 256 range"
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
