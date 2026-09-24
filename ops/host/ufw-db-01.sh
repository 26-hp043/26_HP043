#!/usr/bin/env bash
# ufw-db-01.sh -- db-01 호스트 방화벽 (BlueLog CII).
#
# ⚠️ ufw는 CUBRID 포트(33100)에 관여하지 않는다 (#1641).
#   Docker가 publish한 포트로 오는 패킷은 DNAT 뒤 FORWARD 체인(DOCKER-USER → DOCKER)으로
#   흐르고 호스트의 INPUT 체인을 거치지 않는다. 종전에 이 스크립트가 넣던
#   `ufw allow from <app-01> to any port 33100`은 INPUT 규칙이라 그 트래픽을 본 적이 없다 —
#   있어도 막지 못했고, 없어도 열리지 않는다.
#
#   DB 포트의 2층 방어는 **바인드 주소**다: docker-compose.prod.db.yml이 게시를
#   `${OCI_DB_PRIVATE_IP}:33100:33000`으로 db-01 사설 IP에만 붙여 공용 인터페이스에는
#   소켓이 열리지 않는다. 이 스크립트는 SSH만 다루고, 끝에 그 바인드 주소를 보여 준다.
#
# 사용법:
#   sudo ./ops/host/ufw-db-01.sh
#
# 주의: 이 스크립트는 기존 ufw 규칙을 초기화하지 않는다.
#       ourtax의 규칙이 이미 있을 수 있으므로 추가만 한다.
#       ufw를 켜는 것은 ourtax와 공유하는 호스트 전체에 영향을 주므로 호스트 소유자 확인 뒤 실행한다.

set -euo pipefail

echo "==> BlueLog db-01 ufw 규칙 추가"

# SSH는 이미 열려 있을 것이나, 안전을 위해 확인.
ufw allow 22/tcp comment 'SSH'

# ufw가 비활성이면 활성화한다.
ufw --force enable

echo "==> ufw 상태:"
ufw status verbose

# CUBRID 게시 주소 확인 — ufw가 아니라 여기가 2층이다 (#1641).
# 사설 IP(10.0.1.x)만 보여야 한다. 0.0.0.0이나 [::]가 보이면 compose의 ports가 되돌아간 것이다.
echo "==> CUBRID 게시 주소 (사설 IP만 보여야 한다):"
ss -ltn 'sport = :33100'
echo "==> 완료. OCI Security List(1층)에 33100이 VCN 내부에만 열려 있는지 확인하세요."
