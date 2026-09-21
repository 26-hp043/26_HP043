# OPERATIONS.md -- OCI 배포 운영 가이드

> 최종 갱신: 2026-09-15. 이 문서는 BlueLog(CII 플랫폼)의 OCI 배포 전체를 다룬다.

---

## 1. 아키텍처

```
                    ┌──────────────────────────────────┐
                    │  Cloudflare Pages                 │
                    │  https://bluelog-bx7.pages.dev    │
                    │  (React SPA, Vite 빌드)           │
                    │  + Pages Functions: /api/* 프록시  │
                    └───────────────┬──────────────────┘
                                    │
            화면은 자기 오리진만 부른다 — VITE_API_BASE_URL=/api/v1
            Pages Function이 API_ORIGIN으로 넘긴다 (#1322 · 같은 오리진)
                                    │
  ┌─────────────────────────────────┼─────────────────────────────────┐
  │  OCI ap-seoul-1                 │                                  │
  │                                 ▼                                  │
  │  app-01 (131.186.22.10)         │    db-01 (132.226.170.195)       │
  │  사설 IP: 10.0.1.216            │    사설 IP: 10.0.1.132           │
  │  ┌────────────────────────┐     │    ┌────────────────────────┐   │
  │  │ cii-backend :8001      │  VCN│    │ cii-cubrid :33100      │   │
  │  │ (FastAPI, Python 3.12) │─────┼───>│ (cubrid/cubrid:11.4)   │   │
  │  │ 메모리 제한: 512MB      │    │    │ DB명: cii              │   │
  │  └────────────────────────┘     │    │ 메모리 제한: 512MB      │   │
  │  ┌────────────────────────┐     │    └────────────────────────┘   │
  │  │ ourtax-backend :8000   │     │    ┌────────────────────────┐   │
  │  │ (our-tax, 기존)        │     │    │ ourtax-cubrid :33000   │   │
  │  └────────────────────────┘     │    │ (our-tax, 기존)        │   │
  │                                 │    └────────────────────────┘   │
  │  VM.Standard.E2.1.Micro (1GB)   │    VM.Standard.E2.1.Micro (1GB) │
  └─────────────────────────────────┴─────────────────────────────────┘
```

### 1.1 구성 요소 요약

| 구성 요소 | 기술 | 위치 | URL |
|-----------|------|------|-----|
| 프론트엔드 | React 19 + Vite (SPA) | Cloudflare Pages | https://bluelog-bx7.pages.dev |
| 백엔드 API | FastAPI + Python 3.12 | OCI app-01 | http://131.186.22.10:8001 |
| 데이터베이스 | CUBRID 11.4 | OCI db-01 | 10.0.1.132:33100 (VCN 내부) |
| 이미지 레지스트리 | GitHub Container Registry | GHCR | ghcr.io/26-hp043/bluelog-backend |
| CI/CD | GitHub Actions | GitHub | `.github/workflows/deploy.yml` |
| DNS/CDN | Cloudflare | Cloudflare | (커스텀 도메인 미설정) |

### 1.2 프론트엔드-백엔드 연결 방식 — **같은 오리진** (#1322)

화면과 API는 **같은 오리진**에 있다. 브라우저는 `https://bluelog-bx7.pages.dev/api/v1/…`만
부르고, Pages Function(`frontend/functions/api/[[path]].ts`)이 백엔드로 넘긴다.

```bash
# Cloudflare Pages 배포용 빌드 — 상대 경로를 굳힌다
VITE_API_BASE_URL=/api/v1 npm run build

# 로컬 개발 (Vite 프록시)
npm run dev   # VITE_API_BASE_URL 불필요
```

프록시 상류는 `frontend/wrangler.toml`의 `[vars] API_ORIGIN`이 정한다.

```toml
[vars]
API_ORIGIN = "https://<터널이 준 호스트명>"     # 배포가 시크릿에서 덮어쓴다 (#1496)
```

영향받는 소스 파일:
- `frontend/src/features/voyage-cii/apiProvider.ts` — `DEFAULT_API_BASE_URL`
- `frontend/src/features/annual-simulation/apiProvider.ts` — `DEFAULT_API_BASE_URL`
- `frontend/src/auth/session.ts` — `AUTH_API_BASE`

셋 모두 `import.meta.env.VITE_API_BASE_URL ?? '/api/v1'`이라 **상대 경로가 원래 기본값**이다.

#### ⚠️ 백엔드 주소는 **호스트명**이어야 한다 (#1496)

`API_ORIGIN`에 **IP를 적으면 프록시가 동작하지 않는다.** Cloudflare 공식 문서 원문이다.

> *"For Workers subrequests, requests can only be made to URLs, **not to IP addresses directly**."*
> — [Workers Known issues](https://developers.cloudflare.com/workers/platform/known-issues/)

2026-09-21 실측 — `https://bluelog-bx7.pages.dev/api/v1/health` → **403 · `error code: 1003`**(Direct IP access not allowed). **화면은 200으로 뜨고 `/api/*`만 끊긴다.**

호스트명은 **Cloudflare Tunnel**이 준다(§3.6). 값은 저장소에 두지 않고 시크릿 `API_ORIGIN`으로 넣으면 배포가 `wrangler.toml`에 렌더한다 — 터널을 만들 때 정해지므로 커밋 시점에 알 수 없기 때문이다.

#### 왜 절대 URL + CORS가 아닌가

종전에는 `VITE_API_BASE_URL=http://131.186.22.10:8001/api/v1`이었고, 그 구성에서는
**로그인이 아예 성립하지 않았다.** 세 겹이다.

1. `https` 페이지에서 `http`로 가는 fetch는 브라우저가 **혼합 콘텐츠로 차단**한다 —
   요청 자체가 나가지 않는다.
2. 설령 나가도 `Secure` 쿠키는 **`http` 응답의 `Set-Cookie`에서 거부**된다
   (`auth/session.py`의 `COOKIE_ATTRIBUTES`). `localhost` 예외는 IP 주소에 없다.
3. `SameSite=Lax` 쿠키는 `pages.dev` → `131.186.22.10` **교차 사이트 요청에 실리지
   않는다.** 백엔드에 TLS를 붙여도(#786) `SameSite=None`으로 바꾸기 전에는 같다.

**CORS는 ⑴·⑵·⑶ 중 어느 것도 풀지 않는다.** preflight가 통과해도 쿠키가 저장·전송되지
않기 때문이다 — 그래서 종전 「배포 검증 결과」가 헬스·CORS preflight·미인증 401을 전부
통과시키고도 **로그인만 안 되는** 상태였다.

같은 오리진으로 되돌리면 셋이 함께 사라지고 **백엔드와 `API_SPEC §1.2`는 그대로**다.
`CORS_ALLOW_ORIGINS`는 더 이상 필요하지 않다(`api/main.py`는 미설정이면 CORS 미들웨어를
아예 붙이지 않는다). 남겨 두어도 무해하지만, 같은 오리진에서는 쓰이지 않는다.

> ⚠️ **요청 한도가 전체 공유가 된다.** 백엔드는 `USE_FORWARDED_FOR=false`가 기본이라
> `request.client.host`로 한도를 건다(`api/rate_limit.py`). 프록시 뒤에서는 모든 요청이
> Cloudflare 주소에서 오므로 **여러 사람이 한 버킷을 나눠 쓴다**(`auth` 10/분 ·
> `chat` 10/분). `USE_FORWARDED_FOR=true`로 바꾸려면 **`:8001`에 직접 붙어 헤더를
> 위조할 수 없어야 한다**는 전제가 필요한데(#811 · #786), 지금 그 포트는 열려 있다.
> 후속 이슈로 분리한다.

---

## 2. VM 공존 구조

같은 OCI Always-Free Micro 인스턴스에 our-tax와 BlueLog가 공존한다.

| VM | our-tax | BlueLog |
|----|---------|---------|
| app-01 | ourtax-backend (:8000) | cii-backend (:8001) |
| db-01 | ourtax-cubrid (DB: ourtax, :33000) | cii-cubrid (DB: cii, :33100) |

### 2.1 충돌 방지 매핑

| 자원 | our-tax | BlueLog | 비고 |
|------|---------|---------|------|
| 호스트 포트 (API) | 8000 | **8001** | 컨테이너 내부는 둘 다 8000 |
| 호스트 포트 (DB) | 33000 | **33100** | 컨테이너 내부는 둘 다 33000 |
| 컨테이너 접두사 | `ourtax-` | `cii-` | |
| DB명 | `ourtax` | `cii` | |
| compose 프로젝트 | `our-tax` | `bluelog` | 볼륨명 접두사로 분리 |
| Docker 네트워크 | `ourtax-app-net` | `cii-app-net` | |
| 홈 디렉토리 | `~/our-tax` | `~/bluelog` | VM 내 레포 경로 |
| CUBRID 호스트명 | `ourtax-cubrid` | `cii-cubrid` | databases.txt 충돌 방지 |

### 2.2 메모리 예산 (1GB VM)

```
app-01 (956MB 전체):
  ourtax-backend:  ~82MB  (512MB 제한)
  cii-backend:     ~80MB  (512MB 제한)
  OS + Docker:     ~250MB
  여유:            ~540MB

db-01 (956MB 전체 + 4GB 스왑):
  ourtax-cubrid:   ~33MB  (2GB 제한, 실사용 적음)
  cii-cubrid:      ~30MB  (512MB 제한)
  OS + Docker:     ~200MB
  여유:            ~690MB + 스왑
```

---

## 3. 배포 흐름

### 3.1 자동 배포 (GitHub Actions)

main 브랜치에 다음 경로가 변경되면 자동 실행:

```
src/  alembic/  alembic.ini  pyproject.toml  Dockerfile
docker-compose.prod.*.yml  ops/  frontend/  .github/workflows/deploy.yml
```

워크플로 파일: `.github/workflows/deploy.yml`

```
GitHub Actions (deploy.yml)
  │
  ├─ preflight (#1234) — 필수 시크릿 9종 점검 (누락 시 이름만 출력)
  │
  ├─ build (ubuntu-latest)
  │   └─ Dockerfile (prod target) → GHCR 푸시
  │      - ghcr.io/26-hp043/bluelog-backend:latest
  │      - ghcr.io/26-hp043/bluelog-backend:<sha12>
  │
  ├─ deploy-db (SSH → db-01)
  │   ├─ git pull (~/bluelog)
  │   ├─ ACL 템플릿 치환 (REPLACE_ME_APP_PRIVATE_IP)
  │   ├─ .env 렌더링 (CUBRID_PASSWORD)
  │   ├─ docker compose up -d (CUBRID)
  │   ├─ 브로커 대기 (최대 120초)
  │   └─ 첫 부트 시 ALTER USER dba PASSWORD + 재시작
  │
  ├─ deploy-app (SSH → app-01)
  │   ├─ git pull (~/bluelog)
  │   ├─ CUBRID_PASSWORD URL 인코딩 (SQLAlchemy 호환)
  │   ├─ .env 렌더링 (APP_ENV, DATABASE_URL, CORS, SMTP 등)
  │   ├─ GHCR 로그인 + 이미지 풀
  │   ├─ Alembic 마이그레이션 (one-shot)
  │   ├─ 규제 파라미터 seed
  │   └─ docker compose up -d backend
  │
  └─ health check
      └─ curl http://app-01:8001/api/v1/health (최대 150초)
```

수동 트리거(`workflow_dispatch`) 옵션:
- `force_db_init` (boolean): cubrid-data 볼륨 삭제 후 재초기화. **데이터 손실 비가역적.**

### 3.2 프론트엔드 배포 (Cloudflare Pages)

**자동 (#1236)** — `deploy.yml`의 `deploy-frontend` 잡이 백엔드와 같은 push에서
빌드해 `wrangler pages deploy`로 프로덕션(`--branch main`)에 올린다. 백엔드 잡과
**독립**이다 — OCI 자격증명이 비어 있어도 화면 배포는 시도한다. 필요한 GitHub
시크릿은 `CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_ACCOUNT_ID` 둘뿐이고, 비어 있으면
잡 첫 단계에서 이름만 보고 실패한다.

수동 배포(폴백 — 자동 배포가 깨졌거나 급할 때):

```bash
# 로컬에서 빌드 + 배포
cd frontend
npm ci
VITE_API_BASE_URL=http://131.186.22.10:8001/api/v1 npm run build
wrangler pages deploy dist --project-name bluelog --branch main
```

Cloudflare 인증:
```bash
export CLOUDFLARE_API_TOKEN=<토큰>
export CLOUDFLARE_ACCOUNT_ID=22abb4f21a4c7886292a2a0ecadf331b
```

Pages 프로젝트 정보:
| 항목 | 값 |
|------|-----|
| 프로젝트명 | `bluelog` |
| 프로덕션 URL | https://bluelog-bx7.pages.dev |
| 빌드 명령 | `VITE_API_BASE_URL=... npm run build` |
| 출력 디렉토리 | `frontend/dist` |

### 3.3 수동 백엔드 배포 (SSH)

```bash
# === db-01 ===
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195
cd ~/bluelog

# 코드 업데이트
git fetch origin main && git reset --hard origin/main

# ACL 치환 (최초 1회, 또는 git reset 후)
sed -i "s/REPLACE_ME_APP_PRIVATE_IP/10.0.1.216/g" \
  ops/cubrid/conf/broker_access.conf \
  ops/cubrid/conf/server_access.conf

# .env (최초 1회)
cp .env.db.example .env
# vi .env  →  CUBRID_PASSWORD=<비밀번호>

# 기동
docker compose -f docker-compose.prod.db.yml up -d

# 첫 부트 후 dba 비밀번호 설정
docker compose -f docker-compose.prod.db.yml exec -T cubrid \
  csql -u dba cii -c "ALTER USER dba PASSWORD '<비밀번호>';"
docker compose -f docker-compose.prod.db.yml restart cubrid

# 검증
docker compose -f docker-compose.prod.db.yml exec -T cubrid \
  csql -u dba -p '<비밀번호>' cii -c 'SELECT 1 FROM db_root'
```

```bash
# === app-01 ===
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
cd ~/bluelog

# 코드 업데이트
git fetch origin main && git reset --hard origin/main

# .env (최초 1회)
cp .env.app.example .env
# vi .env  →  아래 값 설정

# .env 필수 값:
#   CUBRID_HOST=10.0.1.132
#   CUBRID_PASSWORD=<비밀번호>
#   DATABASE_URL=cubrid+pycubrid://dba:<URL인코딩된비밀번호>@10.0.1.132:33100/cii
#   CORS_ALLOW_ORIGINS=https://bluelog-bx7.pages.dev
#   APP_PUBLIC_URL=https://bluelog-bx7.pages.dev
#   APP_ENV=staging  (SMTP 미설정 시)  또는  production (SMTP 설정 완료 시)
#   INITIAL_ADMIN_EMAILS=<쉼표로 구분한 이메일>  (가입·로그인마다 이 목록을 관리자로 맞춘다 —
#     비면 새 DB는 관리자 0명이고 역할을 올려 줄 사람이 없다. §4.5 참고, #672 · #1301)
#     ⚠️ 옛 이름 INITIAL_OFFICE_EMAILS는 읽히지 않는다 — 남아 있으면 기동 실패 (#1301)

# GHCR 로그인 (private repo, 또는 로컬 빌드 시 불필요)
echo "ghp_..." | docker login ghcr.io -u USERNAME --password-stdin
docker compose -f docker-compose.prod.app.yml pull backend

# 또는 로컬 빌드
docker build --target prod -t bluelog-backend:local .
# .env에 BACKEND_IMAGE=bluelog-backend:local 설정

# 마이그레이션 + seed
docker compose -f docker-compose.prod.app.yml --profile migrate run --rm migrate
docker compose -f docker-compose.prod.app.yml --profile migrate \
  run --rm migrate python -m cii_platform.db.seed

# 기동
docker compose -f docker-compose.prod.app.yml up -d backend

# 검증
curl http://localhost:8001/api/v1/health
```

### 3.4 데모 데이터 적재·초기화 (#1485)

배포 직후 DB에는 **규제 파라미터만** 있다. 선박·항차는 들어가지 않으므로 대시보드가 비어 있다.

> ⚠️ **「데모 데이터는 `development`·`test`에서만 적재된다」는 말은 틀리다.** `demo_seed.seed_demo()`는 환경을 보지 않는다 — 환경 가드는 **시연 계정(`app_user`) 한 항목 안에만** 있다(`should_seed_demo_user`). `staging`에서 적재하면 **선박·항차는 전부 들어가고 계정만 0행**이 된다.

#### 3.4.1 적재하는 법

GitHub Actions에서 `Deploy to OCI` 워크플로를 **수동 실행**하고 입력을 켠다.

| 입력 | 뜻 |
|---|---|
| `seed_demo` | 데모 데이터를 적재한다 |
| `clear_demo` | 적재 **전에** 기존 데모 데이터를 지운다 |
| 둘 다 | 「지우고 새로 넣기」 — 시각을 새로 잡을 때 |

```bash
gh workflow run deploy.yml -f seed_demo=true
gh workflow run deploy.yml -f seed_demo=true -f clear_demo=true   # 새로 잡기
```

적재되는 것: 선박 **5척** · 항차 **33건**(COMPLETED 11 · IN_PROGRESS 3 · PLANNED 19) · 항차 연료 33 · 정박 구간 4 · 정박 연료 8. 계정은 0행이다.

**자동 배포에서는 켜지지 않는다.** `push` 트리거에는 `inputs`가 없어 빈 문자열이 되고, 셸이 `= "true"`로만 보기 때문이다. `tests/test_deploy_demo_seed.py`가 그 조건이 지워지는 것을 막는다.

#### 3.4.2 ⚠️ 시각이 적재일 기준 상대값이다 (#792)

시드의 날짜는 **적재한 날**을 기준으로 잡힌다. 진행 중 항차의 도착 예정이 `+1`~`+12`일, 관찰선의 최근 구간이 `-12`~`-8`일이다. 그래서 **적재가 오래되면 화면이 의도한 상태에서 멀어진다.**

| 경과 | 나타나는 것 |
|---|---|
| 하루 | 관찰선 진행 항차가 도착 예정을 넘겨 `IN_PROGRESS_PAST_ETA` 대상이 된다 |
| 약 3주 | 최근 구간이 30일 창을 벗어나 `NO_RECENT_DATA`가 된다 |

**적재는 덮어쓰지 않는다** — `_insert_ignoring_existing()`이 `IntegrityError`를 삼키므로 이미 있는 행은 그대로다. 다시 돌려서는 시각이 갱신되지 않고, **지우고 넣어야** 한다.

> **시연·인터뷰 직전에 `clear_demo=true` + `seed_demo=true`로 한 번 돌린다.** 회차가 여러 번이면 회차 사이에도 돌린다 — 둘러보기 세션은 관리자 권한이라 누군가 선박을 지웠을 수 있고, 다시 적재하면 되살아난다(#1486 결정).

#### 3.4.3 지울 때 남는 것

`clear_demo`는 **계산 이력이 참조하는 행을 억지로 지우지 않는다**(#1088). `calculation_run`은 보존 대상이라 그것이 가리키는 항차·선박은 `RESTRICT`에 걸린다. 남긴 수는 출력에 따로 나온다.

```
voyage: 33행 삭제
vessel: 5행 삭제
voyage: 0행 남김 (계산 이력이 참조)
vessel: 0행 남김 (계산 이력이 참조)
```

호스트에서 직접 돌릴 때는 다음과 같다(분리 토폴로지).

```bash
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
cd ~/bluelog
docker compose -f docker-compose.prod.app.yml --profile migrate \
  run --rm -T migrate python -m cii_platform.db.demo_seed          # 적재
docker compose -f docker-compose.prod.app.yml --profile migrate \
  run --rm -T migrate python -m cii_platform.db.demo_seed --clear  # 초기화
```

### 3.5 Cloudflare Tunnel (#1496)

백엔드에 **호스트명과 HTTPS를 주는 통로**다. `cloudflared`가 app-01에서 **아웃바운드로만** 연결하므로 인바운드 포트를 열지 않는다 — `:8001` 직접 노출(`#786`)과 프록시 뒤 요청 한도(`#1483`)도 같은 걸음에 닫힌다.

> 🔴 **이 터널은 우리가 만든 것이 아니라 `ourtax`의 것을 함께 쓴다.** 같은 VM(`ourtax-app`)에서
> **systemd `cloudflared`가 2026-09-12부터 이미 돌고 있었고**, 우리는 거기에 ingress 규칙 한 줄을
> 더했다. 아래 세 가지가 그 결과이며, **모르고 건드리면 남의 서비스가 끊긴다.**
>
> | 사실 | 뜻 |
> |---|---|
> | 커넥터는 **호스트의 systemd**다 (`/usr/local/bin/cloudflared`) | compose의 `cloudflared` 서비스(profile `tunnel`)는 **쓰지 않는다** |
> | ingress는 **로컬 파일** `/etc/cloudflared/config.yml`이 정한다 | 대시보드에서 Public hostname을 추가해도 반영되지 않는다 |
> | catch-all이 **ourtax**(`localhost:8000`)로 간다 | 우리 규칙은 **반드시 catch-all 앞에** 둔다 |

#### 3.5.1 지금 구성

```
브라우저 → bluelog-bx7.pages.dev (Pages Function)
             │ API_ORIGIN
             ▼
        https://bluelog-api.kpubdata.com        ← CNAME → 26dac387-….cfargotunnel.com (proxied)
             ▼
        app-01 systemd cloudflared (터널 26dac387-…, ourtax와 공유)
             ├─ hostname: bluelog-api.kpubdata.com → http://localhost:8001   (cii-backend)
             └─ service(catch-all)                → http://localhost:8000   (ourtax-backend)
```

`/etc/cloudflared/config.yml`:

```yaml
tunnel: ourtax-backend
ingress:
  - hostname: bluelog-api.kpubdata.com
    service: http://localhost:8001
  - service: http://localhost:8000     # ourtax — 반드시 마지막
```

> **왜 `http://localhost:8001`인가** — 커넥터가 **호스트에서** 돌기 때문이다. compose의 컨테이너
> 커넥터였다면 `http://backend:8000`(도커 네트워크 이름)이었을 것이다. 둘을 바꿔 적으면 502가 난다.

#### 3.5.2 GitHub 시크릿

| 시크릿 | 값 | 비고 |
|---|---|---|
| `API_ORIGIN` | `https://bluelog-api.kpubdata.com` | 배포가 `wrangler.toml`에 렌더한다. 없으면 `deploy-frontend`가 **의도적으로 멈춘다** |
| `CLOUDFLARE_TUNNEL_TOKEN` | **비워 둔다** | ⚠️ 아래 참조 |

> ⚠️ **`CLOUDFLARE_TUNNEL_TOKEN`을 등록하지 않는다 (의도).** 등록하면 compose가 `cloudflared`
> 컨테이너를 띄워 **같은 터널에 커넥터가 둘**이 된다. 배포 로그의
> `::warning:: CLOUDFLARE_TUNNEL_TOKEN 미설정 — 터널을 띄우지 않는다`는 **이 구성에서 정상이며,
> 「고쳐야 할 경고」가 아니다.** 터널은 호스트 systemd가 이미 제공한다.

#### 3.5.3 호스트명을 추가·변경할 때

대시보드가 아니라 **VM에서** 한다.

```bash
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
sudo cp /etc/cloudflared/config.yml /etc/cloudflared/config.yml.bak.$(date +%Y%m%d%H%M%S)
sudo vi /etc/cloudflared/config.yml            # 새 hostname 규칙은 catch-all **앞**에
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate   # → OK 확인 필수
sudo systemctl restart cloudflared             # ⚠️ 재시작 수 초간 ourtax도 함께 끊긴다
```

DNS는 Cloudflare에 CNAME으로 만든다 — `<이름>` → `26dac387-2f05-49a5-b807-5172001c2382.cfargotunnel.com`, **proxied**. `ourtax-api.kpubdata.com`이 같은 모양이다.

#### 3.5.4 확인

```bash
curl -i https://bluelog-bx7.pages.dev/api/v1/health   # 200 → 성공
curl -i https://bluelog-api.kpubdata.com/api/v1/health # 터널만 검증 (Pages를 건너뛴다)
curl -i http://131.186.22.10:8001/api/v1/health        # 백엔드만 검증 (터널을 건너뛴다)
```

| 증상 | 원인 |
|---|---|
| `403` · `error code: 1003` | `API_ORIGIN`이 **IP**다. Workers는 IP로 요청하지 못한다 |
| `1033` | DNS는 터널을 가리키는데 **ingress에 그 hostname 규칙이 없다** |
| ourtax 응답(`{"detail":"Not Found"}`)이 온다 | 규칙을 **catch-all 뒤에** 넣었다 |
| `502` | ingress의 `service:` 주소가 틀렸다(`localhost:8001` ↔ `backend:8000` 혼동) |

#### 3.5.5 되돌리기

**`:8001`을 먼저 닫지 않는 것**이 요점 — 터널이 검증될 때까지 직접 호출로 원인을 가릴 수단을 남긴다.

| 단계 | 되돌리는 법 |
|---|---|
| ingress | `sudo cp /etc/cloudflared/config.yml.bak.<타임스탬프> /etc/cloudflared/config.yml && sudo systemctl restart cloudflared` |
| DNS | `bluelog-api.kpubdata.com` 레코드 삭제 |
| `API_ORIGIN` | 시크릿을 지우고 재배포 — `deploy-frontend`가 다시 멈춘다(값이 저장소에 없으므로 커밋 되돌리기는 필요 없다) |
| 터널 자체 | 🔴 **삭제하지 않는다.** ourtax가 같은 터널을 쓴다 |

### 3.7 둘러보기(공개 열람) 운영 (#1486)

가입 없이 서비스를 보여 주는 문이다. **문을 여는 것과 권한을 넓히는 것을 분리한다.**

| 축 | 설정 | 효과 |
|---|---|---|
| 문 | `TOUR_ACCESS_CODE` | 링크에 코드를 실어야 들어온다 (`/login?tour=<코드>`) |
| 문 | `TOUR_PUBLIC=true` | 코드 없이, 로그인 화면의 상시 버튼으로 들어온다 |
| 권한 | (코드 아님) | **항상 읽기 전용** — `auth/tour_policy.py`가 중앙에서 막는다 |

**둘러보기 세션이 못 하는 것** — 쓰기 전체(`POST`·`PATCH`·`PUT`·`DELETE`), `GET /auth/users`
(실제 가입자 이메일), `GET /audit-logs`(이메일·IP·행동 이력), 자기 계정 탈퇴. 할 수 있는 것은
조회와 로그아웃이다.

> **왜 관리자 역할인가** — 연간 시뮬레이션·리포트·감축 계획이 전부 사무직 이상 가드 뒤에 있어,
> 현장직으로 주면 서비스의 절반이 잠긴 화면을 보여 주게 된다. 그래서 **역할은 관리자로 두고
> 쓰기를 막는** 방향을 골랐다.

> ⚠️ **방문자별 임시 계정을 만들지 않는다.** 데이터 격리가 범위 밖이라(`PRD §5.2`) 계정을
> 나눠도 같은 선박·항차를 본다 — 위험을 없애는 것은 계정 수가 아니라 쓰기 차단이다. 계정
> 수명·purge·감사 배선만 늘어난다.

**닫는 법** — `TOUR_PUBLIC`을 비우면 버튼이 사라지고, `TOUR_ACCESS_CODE`까지 비우면 링크도
닫힌다(fail-closed). ⚠️ **이미 발급된 세션은 7일간 살아 있다.**

### 3.6 롤백

#### 3.6.1 지금 떠 있는 것이 어느 커밋인지 답하기 (#789 완료 기준)

```bash
# app-01 — 백엔드 컨테이너가 달린 이미지 태그(=배포 커밋 SHA)
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10 \
  "docker inspect cii-backend --format '{{.Config.Image}}'"
# → ghcr.io/26-hp043/bluelog-backend:<sha>   ← 이 SHA가 배포 커밋이다

# 프론트는 Cloudflare Pages — 대시보드 Deployment History(또는
# https://bluelog-bx7.pages.dev 에서 응답 헤더 x-pages-deployment-id)
```

배포 워크플로 로그(GitHub Actions `Deploy to OCI`)에도 어느 커밋이 나갔는지
남는다. **화면과 서버가 어긋난 것 같으면 이 명령부터** — 어느 쪽이 낡았는지가 정해진다.

#### 3.6.2 이미지 되돌리기 — 마이그레이션이 없던 배포

```bash
# 이전 SHA 태그로 이미지 되돌리기
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
cd ~/bluelog

# .env에서 이미지 태그 변경
sed -i 's|BACKEND_IMAGE=.*|BACKEND_IMAGE=ghcr.io/26-hp043/bluelog-backend:<이전sha>|' .env

# 재기동 (마이그레이션 다운그레이드가 필요하면 별도 처리)
docker compose -f docker-compose.prod.app.yml up -d backend
```

#### 3.6.3 마이그레이션이 섞인 배포의 롤백 — 순서가 있다

주의: 마이그레이션이 포함된 배포는 단순 이미지 교체로 되돌릴 수 없다.
순서는 **백업 먼저, 판정 다음, 교체 마지막**이다.

```bash
# 1) 되돌리기 전에 반드시 현재 상태를 덤프한다 (#827 ⑴ · scripts/db_backup.py)
python3 scripts/db_backup.py backup

# 2) 어느 리비전까지 내려가는지 판정한다 — 되돌릴 수 없는 리비전이 걸려 있으면
#    이미지 교체만으로 끝낸다(스키마를 내리지 않는다).
#    IRREVERSIBLE 목록과 24시간 가드: src/cii_platform/db/migration_guard.py
#    ALLOW_IRREVERSIBLE_DOWNGRADE=<rev> 로만 풀린다.

# 3) 되돌릴 수 있으면: alembic downgrade -1 → 이전 sha 이미지로 교체(위 3.6.2)
#    FK(RESTRICT)로 실패하면 1)의 덤프로 되돌린다(db_backup.py restore).
```

⚠️ `#451`의 사례 — 마이그레이션 다운그레이드가 계산 이력이 있으면 FK(`RESTRICT`)로
막혔다. **되돌릴 수 있다는 가정을 실제로 확인해야 한다.** `db_backup.py`의
복구 리허설(unloaddb → loaddb → 교체)은 CI `docker` 잡이 모든 PR에서 실제로 돌린다.

---

## 4. 보안

### 4.1 DB 접근 4층 방어

```
외부 → OCI Security List(1층) → Host ufw(2층) → CUBRID broker ACL(3층) → CUBRID server ACL(4층)
```

| 층 | 위치 | 설정 파일/도구 | 허용 대상 |
|----|------|---------------|-----------|
| 1 | OCI Security List | OCI 콘솔 | 10.0.0.0/16 → :33100 |
| 2 | db-01 ufw | `ops/host/ufw-db-01.sh` | 10.0.1.216/32 → :33100 |
| 3 | CUBRID broker ACL | `ops/cubrid/conf/broker_access.conf` | cii:dba:10.0.1.216 |
| 4 | CUBRID server ACL | `ops/cubrid/conf/server_access.conf` | 127.0.0.1, 172.* |

ACL 재로드 (재시작 불필요):
```bash
# 브로커 ACL
docker exec cii-cubrid broker_changer BROKER1 access_control reload

# 서버 ACL
docker exec cii-cubrid cubrid server acl reload cii
```

### 4.2 OCI Security List 현재 규칙

`Default Security List for ourtax-vcn` (서울 리전):

| 프로토콜 | 소스 | 포트 | 용도 |
|----------|------|------|------|
| TCP | 0.0.0.0/0 | 22 | SSH |
| TCP | 0.0.0.0/0 | 80 | HTTP |
| TCP | 0.0.0.0/0 | 443 | HTTPS |
| TCP | 0.0.0.0/0 | 8000 | our-tax API |
| TCP | 0.0.0.0/0 | **8001** | **BlueLog API** |
| TCP | 10.0.0.0/16 | 33000 | our-tax CUBRID (VCN 내부) |
| TCP | 10.0.0.0/16 | **33100** | **BlueLog CUBRID (VCN 내부)** |
| ICMP | 10.0.0.0/16 | - | VCN 내부 ping |

### 4.3 CUBRID 비밀번호 제약

- ASCII 문자열, **최대 31바이트** (CUBRID 11.4 ALTER USER 제약)
- 싱글쿼트(`'`) 포함 금지 (ALTER USER SQL 구문 파괴)
- app-01의 DATABASE_URL에서는 **URL 인코딩** 필요:
  ```bash
  python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' 'p@ss'
  # → p%40ss
  ```

### 4.4 GHCR 인증

레포가 private이므로 OCI VM에서 이미지 pull 시 GHCR 로그인 필요.
deploy 워크플로는 `GITHUB_TOKEN`으로 자동 인증한다.

수동 로그인:
```bash
echo "<PAT>" | docker login ghcr.io -u <사용자명> --password-stdin
```

### 4.5 APP_ENV 전환

| APP_ENV | 용도 | MAIL_BACKEND | 가입 게이트 | dev-login · `/docs` · 시연 계정 |
|---------|------|-------------|------------|------------------------------|
| `development` | 로컬 개발 | `console` 허용 | 비활성 | **열림** |
| `test` | 자동 검사 | `console` 허용 | 비활성 | **열림** |
| `staging` | SMTP 없이 배포 검증 | `console` 허용 | 비활성 | **닫힘** (#1058) |
| `production` | 운영 | `smtp` 필수 (console이면 기동 실패) | 필수 | **닫힘** |

현재 상태: **`staging`** (SMTP 미설정).
SMTP 설정 후 `APP_ENV=production`으로 전환한다.

> ⚠️ **`staging`의 마지막 열은 2026-09-15에 바뀌었다 (`#1058`).** 종전 판정은
> `not is_production()`이라 `staging`에서 **`POST /auth/dev-login`(미인증 세션 발급) ·
> `/docs`·`/redoc`·`/openapi.json` · 시연 계정 시드**가 함께 열렸다. 이 배포(app-01:8001,
> OCI Security List `0.0.0.0/0`)에서 앞의 둘이 실제로 200을 냈다 — **누구나 인증 없이
> 세션을 받을 수 있었고**, 시연 계정의 비밀번호는 `README.md`에 공개돼 있다.
>
> 지금은 `config._DEV_SURFACE_ENVS`(= `development`·`test`)가 **여는 목록**으로 판정한다.
> 부정형(`!= production`)은 새 환경이 늘 때 **여는 쪽으로** 틀리고, 여는 목록은 **닫는
> 쪽으로** 틀린다. `staging`이 계속 필요한 이유는 그대로다 — 메일 백엔드(`#524`) ·
> `APP_PUBLIC_URL`(`#809`) · 가입 게이트(`#808`) 가드가 프로덕션 전용이라 SMTP 없이
> 배포를 검증할 자리가 있어야 한다. 이 변경은 **그 자리를 닫힌 채로** 만든다.
>
> **배포 확인 명령** — 세 줄이 모두 이래야 한다.
>
> ```bash
> curl -s -o /dev/null -w '%{http_code}\n' -X POST http://<호스트>:8001/api/v1/auth/dev-login   # 401
> curl -s -o /dev/null -w '%{http_code}\n'      http://<호스트>:8001/docs                        # 401
> docker compose -f docker-compose.prod.app.yml run --rm backend \
>   python -c "from cii_platform.config import _ENV, exposes_dev_surfaces; print(_ENV, exposes_dev_surfaces(_ENV))"
> ```
>
> `README.md` 배포 확인 표가 **`APP_ENV` 확인을 맨 위에 둔 이유**가 이것이다 — 나머지
> 확인 항목(헬스 · 화면 · CORS · 인증 필요 API 401)은 이 가드가 열려 있어도 **전부
> 통과한다.**

> ⚠️ **`INITIAL_ADMIN_EMAILS`가 비면 위 표의 어느 행도 이를 걸러내지 못한다.**
> `validate_initial_admin()`(`role_bootstrap.py`)는 `APP_ENV=production`에서만 기동을
> 거부한다 — **`staging` 행에는 이 가드가 없다.** `#524`가 `production` + `MAIL_BACKEND=console`
> 조합을 기동 실패로 막기 때문에 SMTP 준비 전 배포는 `staging`을 고를 수밖에 없고(`§9.4`),
> 바로 그 `staging`에서 값이 비면 새 DB는 **관리자 0명**으로 조용히 뜬다. 역할 지정
> (`PATCH /auth/users/{id}/role`)은 관리자 전용이라 화면으로는 아무도 올려 줄 수 없다
> (`#672`, `#1290`, `#1301`). `§3.3`의 `.env` 필수 값에 `INITIAL_ADMIN_EMAILS`를 반드시
> 채운다 — 이 목록은 「처음 한 번」이 아니라 「항상 관리자인 사람」이라 가입·로그인마다
> 다시 맞춰진다.
>
> ⚠️ **옛 이름 `INITIAL_OFFICE_EMAILS`는 읽히지 않는다 (`#1301`).** 설정돼 있으면 환경과
> 무관하게 기동이 실패한다 — 조용히 무시하면 「적어 뒀는데 아무 일도 없다」가 되고, 그것이
> `#1290`이 겪은 실패 방식이다.
>
> ⚠️ **`.env`에 적는 것과 컨테이너에 닿는 것은 다른 일이다.** 이 스택의 `backend`에는
> `env_file:`이 없어 `environment:`에 적힌 키만 들어간다. `#1290`이 그 목록에
> `INITIAL_ADMIN_EMAILS`를 추가했으므로, **compose 파일이 그 판 이후인지 먼저 확인한다** —
> 옛 판으로 띄우면 `.env`를 아무리 채워도 앱은 빈 값을 본다(`#508`과 같은 함정).
> `tests/test_compose_env_wiring.py::test_oci_app_compose_uses_every_variable_its_env_example_declares`
> 가 그 어긋남을 막는다.

### 4.6 CORS 미들웨어

`src/cii_platform/api/main.py`에서 `CORS_ALLOW_ORIGINS` 환경변수를 읽어
`CORSMiddleware`를 조건부 등록한다.

| 설정 | 동작 |
|------|------|
| `CORS_ALLOW_ORIGINS=https://bluelog-bx7.pages.dev` | 해당 오리진만 cross-origin 허용 |
| `CORS_ALLOW_ORIGINS=https://a.com,https://b.com` | 쉼표 구분 복수 오리진 |
| 미설정 / 빈 문자열 | CORS 미들웨어 미등록 (같은 출처 배포 시) |

미들웨어 스택 순서 (바깥 → 안쪽):
```
CORSMiddleware → RequestContext → rate_limit → auth → 라우트
```

CORS가 가장 바깥이어야 preflight(OPTIONS)가 auth/rate_limit에 막히지 않는다.

검증 방법:
```bash
# preflight (OPTIONS) — 200이어야 한다
curl -sS -X OPTIONS \
  -H "Origin: https://bluelog-bx7.pages.dev" \
  -H "Access-Control-Request-Method: GET" \
  -D - -o /dev/null http://131.186.22.10:8001/api/v1/health

# 응답에 포함되어야 하는 헤더:
#   access-control-allow-origin: https://bluelog-bx7.pages.dev
#   access-control-allow-credentials: true
#   access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
```

---

## 5. GitHub Actions 시크릿

deploy 워크플로가 사용하는 시크릿. Settings → Secrets and variables → Actions에서 등록.

### 5.1 필수 시크릿

| 시크릿 | 설명 | 예시 값 |
|--------|------|---------|
| `OCI_SSH_PRIVATE_KEY` | PEM 개인키 (패스프레이즈 없음) | `~/.ssh/oci_ourtax_vm` 내용 |
| `OCI_SSH_USER` | SSH 사용자 | `ubuntu` |
| `OCI_DB_HOST` | db-01 공용 IP (SSH 접근용) | `132.226.170.195` |
| `OCI_APP_HOST` | app-01 공용 IP (SSH 접근용) | `131.186.22.10` |
| `OCI_DB_PRIVATE_IP` | db-01 VCN 사설 IP (DATABASE_URL) | `10.0.1.132` |
| `OCI_APP_PRIVATE_IP` | app-01 VCN 사설 IP (ACL 치환) | `10.0.1.216` |
| `CUBRID_PASSWORD` | dba 비밀번호 (<=31바이트, ASCII) | |
| `CORS_ALLOW_ORIGINS` | 프론트엔드 오리진 | `https://bluelog-bx7.pages.dev` |
| `APP_PUBLIC_URL` | 메일 링크 기준 주소 | `https://bluelog-bx7.pages.dev` |
| `INITIAL_ADMIN_EMAILS` | **최초 관리자** 이메일(쉼표 구분). 여기 든 주소는 **가입·로그인할 때마다** 관리자로 맞춰진다 — 「처음 한 번」이 아니라 「항상 관리자인 사람」이다. ⚠️ **비면 관리자 0명으로 뜨고 화면으로는 아무도 역할을 올릴 수 없다** (`#672` · `#1301`). `APP_ENV=production`이면 기동이 거부되지만 **`staging`에는 그 가드가 없어 조용히 뜬다** — 배포 기본값이 `staging`이므로(`#1478`) **반드시 등록한다** (`#1475`) | `a@ex.com,b@ex.com` |
| `CLOUDFLARE_API_TOKEN` | **Cloudflare Pages 배포 토큰**(Pages:Edit). 없으면 `deploy-frontend`가 자격증명 점검에서 멈춰 **화면이 영원히 옛 판**으로 남는다 — 실제로 8회 연속 실패했다 (`#1236` · `#1479`) | |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare 계정 ID (§6.1 공개값) | `22abb4f21a4c7886292a2a0ecadf331b` |
| `API_ORIGIN` | Pages Function이 백엔드를 부를 **호스트명**(`https://` 포함 · §3.5). ⚠️ **IP를 넣으면 프록시가 403(`error 1003`)을 낸다** — Workers는 IP로 요청하지 못한다 (`#1496`) | `https://bluelog-api.kpubdata.com` |

> **위 넷은 「필수」의 뜻이 서로 다르다.** 앞의 9종이 없으면 **백엔드 배포**가 서고, `CLOUDFLARE_*`·`API_ORIGIN`이 없으면 **화면 배포**가 선다. 잡이 갈라져 있어 한쪽이 빨간불이어도 다른 쪽은 초록불이므로, **`Deploy to OCI` 실행의 5잡이 모두 초록불인지**로 확인한다 (`#1201` · `#1479` · `#1496`이 전부 이 자리에서 났다).

### 5.2 권장 시크릿

| 시크릿 | 설명 |
|--------|------|
| `SIGNUP_ALLOWED_DOMAINS` | 가입 허용 메일 도메인 (쉼표 구분) |
| `SIGNUP_INVITE_CODE` | 초대 코드 (16자 이상 권장). 문자 집합 주의는 아래 `TOUR_ACCESS_CODE` 행과 같다 — 모든 시크릿에 해당한다 |
| `MAIL_BACKEND` | `smtp` (프로덕션) |
| `MAIL_FROM` | 발신 주소 (예: `BlueLog <no-reply@example.com>`) |
| `SMTP_HOST` | SMTP 서버 (예: `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP 포트. **비워 두면 587**(submission)이다. **465를 넣으면 implicit TLS**로 붙는다 — 연결하는 순간부터 TLS이고 `SMTP_USE_TLS`와 무관하게 STARTTLS를 걸지 않는다(`RFC 8314 §3.3` · `#1331`) |
| `SMTP_USER` | SMTP 사용자 |
| `SMTP_PASSWORD` | SMTP 비밀번호 |
| `SMTP_USE_TLS` | STARTTLS 사용 여부. 비워 두면 `true`. `SMTP_PORT=465`(implicit TLS)에서는 값과 무관하다 (`#1475`에서 배선) |
| `TOUR_ACCESS_CODE` | **둘러보기 링크의 접근 코드** (`#1486`). `/login?tour=<코드>`로 들어온 사람에게 관리자 열람 세션을 준다. ⚠️ **비면 둘러보기가 닫힌다**(fail-closed) — 가입 게이트와 반대 방향이라 미설정이 안전한 기본값이다. 코드는 URL에 실려 브라우저 히스토리·접근 로그에 남으므로 **32자 이상**을 권하고, 인터뷰가 끝나면 비운다. 다만 **이미 발급된 세션은 7일간 살아 있다**. ⚠️ **문자는 `[A-Za-z0-9_-]`로 한정한다**(`python -c "import secrets;print(secrets.token_urlsafe(32))"`) — `'`가 들어가면 배포 ssh 인용이 끊겨 **잡이 통째로 실패**하고, `$`가 들어가면 compose가 `.env`를 보간해 **값이 조용히 잘린다**(`#1495` 실측). 잘려도 fail-closed라 링크만 거절되지만 원인이 보이지 않는다 |

### 5.3 선택 시크릿

| 시크릿 | 설명 |
|--------|------|
| `APP_ENV` | 배포 환경. **비워 두면 `staging`** (`#524` — SMTP 미설정 배포의 정상 경로 · §4.5). `SMTP_*`를 등록한 뒤 `production`으로 바꾼다. 비워 둔 채로도 `deploy.yml`이 `.env`에 `APP_ENV=staging`을 렌더링하므로 compose 기본값(`production`)으로 떨어지지 않는다 (`#1201`). |
| `CLOUDFLARE_TUNNEL_TOKEN` | 🔴 **비워 둔다 (의도).** 터널 커넥터는 app-01의 **systemd `cloudflared`**가 이미 제공하며 `ourtax`와 공유한다(§3.5). 등록하면 compose가 커넥터를 **하나 더** 띄운다. 배포 로그의 `::warning:: CLOUDFLARE_TUNNEL_TOKEN 미설정`은 **정상 상태의 표시**다 |
| `TOUR_PUBLIC` | **코드 없이 둘러보기를 여는 스위치**(`true`일 때만 열림 · `#1486` 후속). 켜면 로그인 화면에 「로그인 없이 둘러보기」 버튼이 상시 노출되고 접근 코드 없이 들어온다. ⚠️ **접근 코드를 `VITE_`로 넣지 않는다** — 빌드 산출물에 그대로 인라인되어 비밀 링크보다 못해진다. 화면에는 이 **불리언만** 전달된다(`VITE_TOUR_PUBLIC`). 문이 넓어져도 권한은 그대로다 — 둘러보기 세션은 **읽기 전용**이다(§3.7) |
| `LLM_API_KEY` | Anthropic Claude API 키 (챗봇 기능. 비어있으면 챗봇만 비활성) |

---

## 6. Cloudflare Pages 설정

### 6.1 프로젝트 정보

| 항목 | 값 |
|------|-----|
| Cloudflare 계정 ID | `22abb4f21a4c7886292a2a0ecadf331b` |
| 프로젝트명 | `bluelog` |
| 프로덕션 URL | https://bluelog-bx7.pages.dev |
| 프로덕션 브랜치 | `main` |
| 배포 방식 | wrangler CLI 직접 업로드 (Git 연동 아님) |

### 6.2 배포 명령

```bash
# 환경변수 설정
export CLOUDFLARE_API_TOKEN=<토큰>
export CLOUDFLARE_ACCOUNT_ID=22abb4f21a4c7886292a2a0ecadf331b

# 빌드
cd frontend
npm ci
VITE_API_BASE_URL=http://131.186.22.10:8001/api/v1 npm run build

# 배포
wrangler pages deploy dist --project-name bluelog --branch main
```

### 6.3 커스텀 도메인 추가 (향후)

```bash
wrangler pages project add-domain bluelog <도메인>
```

도메인 추가 시 변경 필요:
1. 백엔드 `CORS_ALLOW_ORIGINS`에 새 도메인 추가
2. 프론트엔드 빌드 시 `VITE_API_BASE_URL` 유지 (백엔드 IP는 동일)
3. `APP_PUBLIC_URL`을 새 도메인으로 변경

---

## 7. 파일 구조

```
26_HP043/
  ├── docker-compose.prod.app.yml    # app-01: backend + migrate
  ├── docker-compose.prod.db.yml     # db-01: CUBRID
  ├── .env.app.example               # app-01 환경변수 템플릿
  ├── .env.db.example                # db-01 환경변수 템플릿
  ├── .github/workflows/
  │   ├── ci.yml                     # CI (lint, test, docker smoke)
  │   └── deploy.yml                 # OCI 배포 자동화
  ├── ops/
  │   ├── cubrid/conf/
  │   │   ├── cubrid.conf            # CUBRID 서버 설정 (메모리, ACL)
  │   │   ├── cubrid_broker.conf     # 브로커 설정 (query_editor OFF, ACL ON)
  │   │   ├── broker_access.conf     # 브로커 ACL (app-01 IP 템플릿)
  │   │   ├── server_access.conf     # 서버 ACL (loopback + docker bridge)
  │   │   └── README.md              # ACL 설정 가이드
  │   └── host/
  │       ├── ufw-db-01.sh           # db-01 방화벽 스크립트
  │       └── setup-zram-swap.sh     # 1GB VM 메모리 최적화
  └── docs/
      └── OPERATIONS.md              # 이 문서
```

---

## 8. 모니터링

### 8.1 헬스 체크

```bash
# 외부에서 (브라우저 / curl)
curl http://131.186.22.10:8001/api/v1/health
# → {"data":{"status":"ok","version":"0.1.0",...}}

# app-01 내부에서
curl http://localhost:8001/api/v1/health

# Cloudflare Pages 프론트엔드
curl -o /dev/null -w "%{http_code}" https://bluelog-bx7.pages.dev/
# → 200
```

### 8.2 로그

```bash
# 백엔드 로그 (app-01)
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
docker logs cii-backend --tail=100 -f

# CUBRID 로그 (db-01)
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195
docker logs cii-cubrid --tail=100 -f
```

### 8.2.1 구조화 로그 — 장애 때 어느 파일을 어떻게 보나 (#827 ⑵)

프로덕션 compose가 `LOG_FILE=/app/logs/api.jsonl`을 설정한다(단일 호스트 `docker-compose.prod.yml`과 분리 토폴로지 `docker-compose.prod.app.yml` **둘 다** — 종전에는 앞의 것만 설정해 app-01에서 이 절차가 「No such file」로 끝났다 · `#1331`). 접근 요약(쿼리스트링·본문
**없이** — 토큰·비밀번호가 로그로 새지 않는다)과 예외 스택이 **JSON 한 줄**로 쌓이고,
10MB × 5개로 회전한다. 볼륨(`app-logs`)에 남으므로 컨테이너를 다시 만들어도 유지된다.

```bash
# app-01 — 파일이 어디에 있나
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10
docker exec cii-backend sh -c 'ls -lh /app/logs/'

# 5xx만 골라 보기 — 장애 되짚기의 첫 동작
docker exec cii-backend sh -c \
  'grep "\"level\": \"ERROR\"" /app/logs/api.jsonl | tail -20'

# 한 요청의 전 과정 되짚기 — 응답 meta의 request_id로 잇는다
docker exec cii-backend sh -c \
  'grep "<request_id>" /app/logs/api.jsonl'

# jq가 있으면 필드로 본다
docker exec cii-backend sh -c \
  'cat /app/logs/api.jsonl | tail -100 | jq -c "{ts,level,path,status,duration_ms}"'
```

줄의 모양 — 키는 `ts`·`level`·`logger`·`message`, 접근 로그(`cii_platform.access`)는
`request_id`·`method`·`path`·`status`·`duration_ms`·`client`를 더 싣는다. 예외 기록은
`exc` 키에 스택 텍스트가 들어간다.

> **콘솔(`docker logs`)과의 관계** — 콘솔은 사람이 읽는 짧은 형식, 파일이 JSON이다.
> uvicorn 기본 접근 로그는 꺼져 있다(쿼리스트링을 남겨 토큰이 새는 결함이 있어서,
> #827 ⑵). 접근 기록은 이 파일 하나에서 본다.

### 8.3 리소스 모니터링

```bash
# 메모리 사용량
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10 "free -m"
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195 "free -m"

# 컨테이너별 리소스
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10 \
  "docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'"
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195 \
  "docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'"
```

### 8.4 디스크 사용량

```bash
# Docker 이미지/볼륨
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@131.186.22.10 "docker system df"
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195 "docker system df"
```

---

## 9. 문제 해결

### 9.1 CUBRID "Incorrect or missing password"

원인: healthcheck의 csql에 비밀번호가 빠졌거나, ALTER USER 후 브로커를 재시작하지 않았다.

```bash
# 비밀번호 재설정
docker exec cii-cubrid csql -u dba -p OLD_PASSWORD cii \
  -c "ALTER USER dba PASSWORD 'NEW_PASSWORD';"

# 브로커 재시작 (CAS 워커 캐시 갱신)
docker restart cii-cubrid

# 검증
docker exec cii-cubrid csql -u dba -p NEW_PASSWORD cii \
  -c 'SELECT 1 FROM db_root'
```

### 9.2 "Failed to connect to database server, 'cii', on &lt;hostname&gt;"

원인: CUBRID가 databases.txt에 기록한 호스트명과 현재 컨테이너 호스트명 불일치.

확인:
```bash
docker exec cii-cubrid cat /var/lib/cubrid/databases/databases.txt
```

`hostname: cii-cubrid`이 docker-compose.prod.db.yml에 고정되어 있는지 확인.
볼륨이 다른 호스트명으로 초기화됐다면 `force_db_init`으로 재생성 (데이터 손실).

### 9.3 app-01에서 db-01 연결 실패

```bash
# 1. 네트워크 연결 확인
ssh ubuntu@131.186.22.10 "nc -vz 10.0.1.132 33100 -w 3"

# 2. 실패 시: OCI Security List에 33100이 있는지 확인
# OCI 콘솔 → Networking → Virtual Cloud Networks → ourtax-vcn → Security Lists

# 3. db-01 ufw 확인
ssh ubuntu@132.226.170.195 "sudo ufw status"

# 4. CUBRID 브로커 상태 확인
ssh ubuntu@132.226.170.195 "docker exec cii-cubrid cubrid broker status"
```

### 9.4 백엔드 기동 실패: MAIL_BACKEND=console 프로덕션 오류

```
RuntimeError: MAIL_BACKEND=console은 프로덕션에서 사용할 수 없습니다
```

해결:
- SMTP 설정 완료 전: `.env`에서 `APP_ENV=staging` 설정
- SMTP 설정 후: `APP_ENV=production` + `MAIL_BACKEND=smtp` + SMTP 자격증명

### 9.5 메모리 부족 (OOM)

1GB VM에 두 프로젝트가 공존하므로 OOM 가능.

```bash
# 메모리 확인
free -m
docker stats --no-stream

# zram 스왑 설정 (최초 1회)
sudo ~/bluelog/ops/host/setup-zram-swap.sh

# 불필요한 이미지 정리
docker image prune -a
```

### 9.6 포트 충돌

```bash
# BlueLog: 8001(API), 33100(DB)
# our-tax: 8000(API), 33000(DB)
docker ps --format 'table {{.Names}}\t{{.Ports}}'

# 특정 포트 점유 확인
ss -tlnp | grep -E '8000|8001|33000|33100'
```

### 9.7 Cloudflare Pages CORS 오류

브라우저 콘솔에 `CORS policy` 오류가 나면:

1. 백엔드 `CORS_ALLOW_ORIGINS`에 Cloudflare Pages 도메인이 있는지 확인
2. 프로토콜 일치 확인 (`https://` vs `http://`)
3. 후행 슬래시 없이 정확한 오리진 (예: `https://bluelog-bx7.pages.dev`)

```bash
# app-01에서 확인
ssh ubuntu@131.186.22.10 "grep CORS ~/bluelog/.env"

# 변경 후 재시작
ssh ubuntu@131.186.22.10 "cd ~/bluelog && docker compose -f docker-compose.prod.app.yml up -d backend"
```

---

## 10. 운영 체크리스트

### 10.1 현재 상태 (2026-09-15)

- [x] OCI VM 2대 확보 (app-01, db-01)
- [x] CUBRID 기동 (db-01, DB명 cii, 포트 33100)
- [x] 백엔드 배포 (app-01, 포트 8001, APP_ENV=staging)
- [x] Alembic 마이그레이션 완료
- [x] 규제 파라미터 seed 완료 (63행: fuel_type 8, regulation_year 8, cii_reference_line 20, cii_rating_boundary 14, simulation_parameter 3, weather_model_parameter 10)
- [x] OCI Security List 규칙 추가 (8001/tcp 0.0.0.0/0, 33100/tcp 10.0.0.0/16)
- [x] Cloudflare Pages 프론트엔드 배포 (https://bluelog-bx7.pages.dev)
- [x] CORS 미들웨어 추가 (`CORSMiddleware`, `CORS_ALLOW_ORIGINS` 환경변수)
- [x] CORS 설정 적용 (bluelog-bx7.pages.dev → app-01:8001)
- [x] 헬스 체크 정상 확인

### 10.2 배포 검증 결과 (2026-09-15 11:03 UTC)

| 테스트 | 결과 | 비고 |
|--------|------|------|
| 백엔드 헬스 | `{"status":"ok","version":"0.1.0"}` | numpy, rng, pdf_font 모두 ok |
| Cloudflare Pages | HTTP 200, 2628 bytes | SPA index.html 정상 |
| CORS preflight | HTTP 200, allow-origin 헤더 포함 | OPTIONS 요청 통과 |
| 인증 필요 API | HTTP 401 UNAUTHORIZED | 정상 (로그인 필요) |
| CUBRID fuel_type | 8행 | seed 정상 적용 |
| cii-backend 컨테이너 | Up, healthy | 포트 8001 |
| cii-cubrid 컨테이너 | Up, healthy | 포트 33100 |

### 10.3 배포 검증 결과 (2026-09-21 00:4x UTC · 터널 경유 전 구간)

`#1496` 해결 뒤 **화면 → Pages Function → 터널 → 백엔드 → DB** 전 구간을 실측했다.

| 확인 | 결과 | 비고 |
|---|---|---|
| 화면 | `200` | `https://bluelog-bx7.pages.dev` · `/login` SPA 폴백도 `200` |
| **프록시 경유 헬스** | `200` | `/api/v1/health` — 종전 `403 (error 1003)` |
| 터널 직결 | `200` | `https://bluelog-api.kpubdata.com/api/v1/health` |
| 백엔드 직결 | `200` | `http://131.186.22.10:8001/api/v1/health` (`#786` 전까지 유지) |
| **클라우드 로그인** | **성공** | `#1322` 완료 기준 — 아래 상세 |
| 미인증 업무 API | `401` | 쿠키 없이 `/fleet/summary` |
| `dev-login` · `/docs` | `401` · `401` | `staging` 자세 유지 (`#1058` · §4.5) |
| 배포 파이프라인 | **5잡 초록불** | run `35548027088`(workflow_dispatch) |

**로그인 상세** (`#1322` — 「혼합 콘텐츠·Secure 쿠키·SameSite로 로그인이 성립하지 않는다」의 해소 증거)

```
POST /api/v1/auth/signup        → 201  (role FIELD)
  set-cookie: sid=…;  HttpOnly; Path=/; SameSite=lax; Secure      ← pages.dev 오리진
  set-cookie: csrf=…;           Path=/; SameSite=lax; Secure
GET  /api/v1/auth/me            → 200  (세션 유효)
GET  /api/v1/fleet/summary?year=2026 → 200  (선박 5척 · 등급 B1 C1 D1 E2)
DELETE /api/v1/auth/me (X-CSRF-Token) → 204, 이후 /auth/me → 401   ← 검증 계정 정리
```

> **왜 이제 되는가** — 화면과 API가 **같은 오리진**(`pages.dev`)이 됐기 때문이다. Pages Function이
> `/api/*`를 터널 호스트명으로 넘기므로 브라우저에게는 동일 출처이고, `SameSite=lax` · `Secure`
> 쿠키가 그대로 저장·전송된다. 종전 구조(`https` 화면 → `http://IP:8001`)에서는 세 겹으로 막혔다.

### 10.4 남은 작업

- [x] ~~**재배포 필요**(`#1177`)~~ — 해소. 2026-09-21 실측으로 `dev-login`·`/docs` 둘 다 **401**이다(§10.3). ⚠️ 그 대신 아래 `INITIAL_ADMIN_EMAILS`가 **더 급해졌다** — `dev-login`이 닫힌 지금, 관리자 0명이면 사무직·관리자 화면에 들어갈 길이 없다
- [ ] **`INITIAL_ADMIN_EMAILS` 설정** — ⚠️ **`.env`에 적는 것만으로는 닿지 않는다.** `docker-compose.prod.app.yml`의 `backend`에는 `env_file:`이 없고 `environment:` 목록만 주입되는데, `#1290` 이전 판에는 이 키가 그 목록에 **없었다** — compose가 `.env`를 읽는 것은 `${VAR}` 치환용이지 컨테이너 주입이 아니다(`#508`과 같은 함정). 그러므로 **`#1290`의 compose 변경을 함께 내려받은 뒤** `.env`를 채운다. 값을 채우고 해당 계정으로 다시 로그인하면 해소된다(`§3.3`, `§4.5`, `#672`, `#1290`)
  - 지금 사무직이 몇 명인지는 DB가 답한다 — `SELECT email, [role] FROM app_user WHERE is_deleted = false` (CUBRID에서 `role`은 예약어라 대괄호가 필요하다)
- [ ] **`TOUR_ACCESS_CODE` 설정** — 미등록이라 **둘러보기 링크가 닫혀 있다**(fail-closed · `#1486`). 로그인 없이 화면을 보여 줄 유일한 경로이므로 시연 전에 정한다
- [ ] **SMTP 설정** → `APP_ENV=production` 전환 (#787)
- [x] ~~**GitHub Secrets 등록**~~ — 완료(12종). 백엔드 9종(`#1201`) · `CLOUDFLARE_API_TOKEN`(`#1479`) · `API_ORIGIN`(`#1496`). 재발은 `test_deploy_secrets_are_listed_in_the_operations_secret_tables`가 막는다
- [ ] **커스텀 도메인** → 화면(Pages)은 아직 `bluelog-bx7.pages.dev`다. **API는 `bluelog-api.kpubdata.com`으로 확보**됐다(`#1496` · §3.5). 화면 도메인을 붙이면 `CORS_ALLOW_ORIGINS`·`APP_PUBLIC_URL`도 함께 바꾼다 (#785)
- [x] ~~**CUBRID 비밀번호 설정**~~ — 완료. `CUBRID_PASSWORD` 시크릿이 배포·헬스체크 양쪽에 쓰인다
- [ ] **ufw 활성화** → `ops/host/ufw-db-01.sh` 실행
- [ ] **zram 스왑** → `ops/host/setup-zram-swap.sh` 실행 (이미 our-tax에서 적용됐을 수 있음)
- [ ] **백업 절차** → 정기 백업 스크립트 (#788)
- [ ] **모니터링** → 헬스 체크 주기적 확인 (#790)
