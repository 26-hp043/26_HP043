#!/usr/bin/env bash
# 개발 서버 실행 스크립트
# db 컨테이너가 healthy 상태가 될 때까지 기다린 뒤 app을 실행한다.
# (docker-compose의 depends_on: service_healthy 조건이 대기를 보장하지만,
#  스크립트에서도 기동 순서를 명시적으로 제어해 로그를 분리한다.)
set -euo pipefail

# 저장소 루트에서 실행 (스크립트 위치 기준)
cd "$(dirname "$0")/.."

echo "▶ db 컨테이너 기동 및 healthcheck 대기..."
docker compose up -d --wait db

echo "▶ app 컨테이너 기동 (--build, 포그라운드)..."
docker compose up --build app
