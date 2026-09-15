# OPERATIONS.md -- OCI 배포 운영 가이드

## 1. 아키텍처

```
Cloudflare Pages (프론트엔드 SPA)
        |
        | CORS (CORS_ALLOW_ORIGINS)
        v
  app-01 (131.186.22.10)              db-01 (132.226.170.195)
  +---------------------------+       +---------------------------+
  | cii-backend :8001->:8000  |       | cii-cubrid :33100->:33000         |
  | (GHCR image)              | ----> | (cubrid/cubrid:11.4)      |
  |                           | VCN   |                           |
  | ourtax-backend :8000 (기존)|      | ourtax-cubrid :33000 (기존)|
  +---------------------------+       +---------------------------+
  VM.Standard.E2.1.Micro (1GB)        VM.Standard.E2.1.Micro (1GB)
  리전: ap-seoul-1                     리전: ap-seoul-1
```

- **프론트엔드**: Cloudflare Pages (React SPA, Vite 빌드)
- **백엔드**: OCI app-01, Docker 컨테이너, 포트 8001 (ourtax가 8000 사용)
- **DB**: OCI db-01, CUBRID 11.4, DB명 `cii`
- **이미지 레지스트리**: GitHub Container Registry (GHCR)

## 2. VM 공존 구조

같은 OCI Micro 인스턴스에 our-tax와 BlueLog가 공존한다.

| VM | our-tax | BlueLog |
|----|---------|---------|
| app-01 | ourtax-backend (:8000) | cii-backend (:8001) |
| db-01 | ourtax-cubrid (DB: ourtax) | cii-cubrid (DB: cii) |

### 충돌 방지

- **포트**: BlueLog 백엔드는 호스트 8001 -> 컨테이너 8000
- **컨테이너명**: `cii-` 접두사 (our-tax는 `ourtax-`)
- **DB명**: `cii` (our-tax는 `ourtax`)
- **볼륨명**: `bluelog_cubrid-data` (compose 프로젝트명으로 분리)
- **네트워크**: `cii-app-net` (our-tax는 `ourtax-app-net`)
- **레포 디렉토리**: `~/bluelog` (our-tax는 `~/our-tax`)

## 3. 배포 흐름

### 3.1 자동 배포 (GitHub Actions)

main 브랜치에 다음 경로가 변경되면 자동 실행:
`src/`, `alembic/`, `Dockerfile`, `docker-compose.prod.*.yml`, `ops/`, `deploy.yml`

```
GitHub Actions
  |
  +-- build: Dockerfile(prod) -> GHCR 푸시 (:latest + :<sha>)
  |
  +-- deploy-db: SSH db-01 -> git pull -> CUBRID 기동 (멱등)
  |
  +-- deploy-app: SSH app-01 -> git pull -> GHCR pull
  |                -> Alembic migrate -> seed -> backend up
  |
  +-- health check: curl http://app-01:8001/api/v1/health
```

### 3.2 수동 배포

```bash
# --- db-01 ---
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195
cd ~/bluelog

# ACL 치환 (최초 1회)
sed -i "s/REPLACE_ME_APP_PRIVATE_IP/10.0.1.216/g" \
  ops/cubrid/conf/broker_access.conf \
  ops/cubrid/conf/server_access.conf

cp .env.db.example .env
# .env 편집: CUBRID_PASSWORD 설정

docker compose -f docker-compose.prod.db.yml up -d

# 첫 부트 후 dba 비밀번호 설정
docker compose -f docker-compose.prod.db.yml exec -T cubrid \
  csql -u dba cii -c "ALTER USER dba PASSWORD 'YOUR_PASSWORD';"
docker compose -f docker-compose.prod.db.yml restart cubrid


# --- app-01 ---
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
cd ~/bluelog

cp .env.app.example .env
# .env 편집: CUBRID_HOST, CUBRID_PASSWORD, CORS 등

# GHCR 로그인 (private repo)
echo "ghp_..." | docker login ghcr.io -u USERNAME --password-stdin

# 이미지 풀
docker compose -f docker-compose.prod.app.yml pull backend

# 마이그레이션 + seed
docker compose -f docker-compose.prod.app.yml --profile migrate \
  run --rm migrate
docker compose -f docker-compose.prod.app.yml --profile migrate \
  run --rm migrate python -m cii_platform.db.seed

# 기동
docker compose -f docker-compose.prod.app.yml up -d backend

# 확인
curl http://localhost:8001/api/v1/health
```

## 4. 보안

### 4.1 DB 접근 4층 방어

| 층 | 위치 | 설정 |
|----|------|------|
| 1 | OCI Security List | app-01 사설 IP만 :33100 허용 |
| 2 | db-01 ufw | `ops/host/ufw-db-01.sh` |
| 3 | CUBRID broker ACL | `ops/cubrid/conf/broker_access.conf` |
| 4 | CUBRID server ACL | `ops/cubrid/conf/server_access.conf` |

### 4.2 CUBRID 비밀번호 제약

- ASCII 문자열, **최대 31바이트**
- 싱글쿼트(`'`) 포함 금지 (ALTER USER 구문 파괴)
- app-01의 .env에서는 URL 인코딩 필요 (SQLAlchemy)

### 4.3 GHCR 인증

이미지가 private repo에 속하므로 OCI VM에서 pull 시 GHCR 로그인 필요.
deploy 워크플로는 `GITHUB_TOKEN`으로 자동 인증한다.

## 5. GitHub Actions 시크릿

| 시크릿 | 설명 | 필수 |
|--------|------|------|
| `OCI_SSH_PRIVATE_KEY` | PEM 개인키 (~/.ssh/oci_ourtax_vm) | O |
| `OCI_SSH_USER` | SSH 사용자 (`ubuntu`) | O |
| `OCI_DB_HOST` | db-01 공용 IP (`132.226.170.195`) | O |
| `OCI_APP_HOST` | app-01 공용 IP (`131.186.22.10`) | O |
| `OCI_DB_PRIVATE_IP` | db-01 사설 IP (`10.0.1.132`) | O |
| `OCI_APP_PRIVATE_IP` | app-01 사설 IP (`10.0.1.216`) | O |
| `CUBRID_PASSWORD` | dba 비밀번호 (<=31바이트) | O |
| `CORS_ALLOW_ORIGINS` | 프론트엔드 오리진 | O |
| `APP_PUBLIC_URL` | 메일 링크 기준 주소 | O |
| `SIGNUP_ALLOWED_DOMAINS` | 가입 허용 도메인 | 권장 |
| `SIGNUP_INVITE_CODE` | 초대 코드 | 권장 |
| `MAIL_BACKEND` | `smtp` (프로덕션) | 권장 |
| `MAIL_FROM` | 발신 주소 | 권장 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP 설정 | 권장 |
| `LLM_API_KEY` | Anthropic Claude API 키 | 선택 |

## 6. 모니터링

### 헬스 체크

```bash
# app-01에서
curl http://localhost:8001/api/v1/health

# 외부에서
curl http://131.186.22.10:8001/api/v1/health
```

### 로그

```bash
# app-01
docker logs cii-backend --tail=100 -f

# db-01
docker logs cii-cubrid --tail=100 -f
```

### 컨테이너 상태

```bash
# app-01
docker ps --filter name=cii

# db-01
docker ps --filter name=cii
```

## 7. 문제 해결

### CUBRID "Incorrect or missing password"

healthcheck의 csql에 비밀번호가 빠졌거나, ALTER USER 후 브로커를 재시작하지 않았다.

```bash
# 비밀번호 재설정
docker exec cii-cubrid csql -u dba -p OLD_PASSWORD cii \
  -c "ALTER USER dba PASSWORD 'NEW_PASSWORD';"

# 브로커 재시작 (CAS 워커 캐시 갱신)
docker restart cii-cubrid
```

### "Failed to connect to database server, 'cii', on <hostname>"

CUBRID가 databases.txt에 기록한 호스트명과 현재 컨테이너 호스트명이 불일치.
`hostname: cii-cubrid`이 docker-compose.prod.db.yml에 고정되어 있는지 확인.
볼륨이 다른 호스트명으로 초기화됐다면 `force_db_init`으로 재생성.

### 메모리 부족

1GB VM에 두 프로젝트가 공존하므로 OOM 가능.

```bash
# 메모리 확인
free -m
docker stats --no-stream

# zram 스왑 설정 (최초 1회)
sudo ./ops/host/setup-zram-swap.sh
```

### 포트 충돌

BlueLog는 8001, our-tax는 8000. 확인:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```
