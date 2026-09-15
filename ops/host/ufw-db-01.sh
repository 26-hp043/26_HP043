#!/usr/bin/env bash
# ufw-db-01.sh -- db-01 방화벽 설정 (BlueLog CII).
#
# app-01의 사설 IP만 CUBRID 포트(33000)에 접근할 수 있도록 제한한다.
# OCI Security List와 이중으로 적용한다 (방어 2층).
#
# 사용법:
#   sudo APP_01_PRIVATE_IP=10.0.1.216 ./ops/host/ufw-db-01.sh
#
# 주의: 이 스크립트는 기존 ufw 규칙을 초기화하지 않는다.
#       ourtax의 규칙이 이미 있을 수 있으므로 추가만 한다.

set -euo pipefail

if [ -z "${APP_01_PRIVATE_IP:-}" ]; then
  echo "ERROR: APP_01_PRIVATE_IP 환경변수를 설정하세요." >&2
  echo "  sudo APP_01_PRIVATE_IP=10.0.1.216 $0" >&2
  exit 1
fi

echo "==> BlueLog db-01 ufw 규칙 추가 (app-01=${APP_01_PRIVATE_IP})"

# SSH는 이미 열려 있을 것이나, 안전을 위해 확인.
ufw allow 22/tcp comment 'SSH'

# CUBRID: app-01 사설 IP만 허용.
ufw allow from "${APP_01_PRIVATE_IP}" to any port 33000 proto tcp \
  comment "BlueLog CUBRID from app-01"

# ufw가 비활성이면 활성화한다.
ufw --force enable

echo "==> ufw 상태:"
ufw status verbose
echo "==> 완료. OCI Security List에도 동일 규칙이 있는지 확인하세요."
