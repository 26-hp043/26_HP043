# OPERATIONS.md -- OCI 배포 운영 가이드

> 최종 갱신: 2026-09-26 (§1.2.1 감사 로그·세션 IP도 같은 판정 · #1889 · §3.1.1 시연 동결 `DEPLOY_FROZEN` · §3.6.1 헬스 `commit` 확인 · #789 · §9.2.1 이름 있는 볼륨으로 옮기기 — 배포가 옮기기 전 상태를 보고 멈춘다 · #1867 · §1.2.1 프록시 서명 헤더 · #1483). 이 문서는 BlueLog(CII 플랫폼)의 OCI 배포 전체를 다룬다.

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

#### 1.2.1 요청 한도가 사람마다 세어지게 — 프록시 서명 헤더 (#1483)

프록시 뒤에서는 모든 요청이 터널을 거쳐 `localhost`로 들어와 `request.client.host`가
**모든 사용자에게 같다.** 그대로면 여러 사람이 한 버킷을 나눠 쓴다(`auth` 10/분 ·
`chat` 10/분).

**`CF-Connecting-IP`로는 풀리지 않는다.** 화면(`pages.dev`)과 API(`kpubdata.com`)가 다른
Cloudflare 영역이라, 영역 사이 서브리퀘스트에는 Cloudflare가 그 헤더를 Worker 주소
`2a06:98c0:3600::103` 하나로 다시 쓴다(Cloudflare Docs *HTTP headers*).
**`USE_FORWARDED_FOR=true`도 답이 아니다** — `:8001`이 열려 있어 헤더를 위조할 수 있다.

그래서 이렇게 한다.

| 자리 | 하는 일 |
|---|---|
| Pages Function (`frontend/functions/_proxy.ts`) | 브라우저 요청의 `cf-connecting-ip`(엣지가 붙인 값 — 사용자가 위조하지 못한다)를 `X-BlueLog-Client-IP`에 옮겨 담고 `X-BlueLog-Proxy-Secret`에 비밀 값을 싣는다. 브라우저가 같은 이름으로 보낸 헤더는 뗀다 |
| 백엔드 (`api/rate_limit.py` `client_ip`) | 비밀 값이 **맞을 때만**(`hmac.compare_digest`) 그 IP로 센다. 없거나 틀리면 헤더를 무시하고 종전 규칙대로 — `:8001`로 직접 들어와 헤더를 적어도 위조가 되지 않는다 |
| 감사 로그 · 세션 (`audit_client_ip` · #1889) | 위와 **같은 판정**으로 `audit_log.ip_address`·`user_session.ip_address`를 적는다. 판정 함수는 하나다 — 라우트마다 소켓 상대를 직접 읽던 자리를 모두 옮겼다. 알 수 없으면 `unknown` 대신 NULL |
| 비밀 값 | GitHub 시크릿 `PROXY_CLIENT_IP_SECRET` 하나(§5.1). 배포가 Pages 시크릿과 app-01 `.env`에 같은 값을 넣는다 |
| 세는 단위 | IPv4는 주소, **IPv6는 `/64` 대역**(`limit_key`). IPv6 가입자는 `/64`를 통째로 받아, 주소마다 세면 대역 안에서 주소를 바꿔 한도를 피할 수 있다. 로그의 `client`는 묶지 않은 주소다 |

**배포 뒤 확인** — 백엔드 기동 로그에 `요청 한도 IP 판정: 프록시 서명 헤더 켜짐`이 찍힌다.
`꺼짐`이면 비밀 값이 배포 경로 어딘가에서 빠진 것이다. 접근 로그(`api.jsonl`)의
`client`는 판정된 IP, `peer`는 소켓 상대(터널이면 `127.0.0.1`)다. 서로 다른 두 네트워크에서
로그인했을 때 `client`가 둘로 찍히면 끝이다.

`:8001`을 닫는 일은 이것과 독립이다 — `#786`이 헬스체크 이전과 함께 한다.

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
app-01 (956MB 전체 + 2GB 스왑):
  ourtax-backend:  ~82MB  (512MB 제한)
  cii-backend:     ~80MB  (512MB 제한)
  OS + Docker:     ~250MB
  여유:            ~540MB + 스왑

db-01 (956MB 전체 + 4GB 스왑):
  ourtax-cubrid:   ~33MB  (2GB 제한, 실사용 적음)
  cii-cubrid:      ~30MB  (512MB 제한)
  OS + Docker:     ~200MB
  여유:            ~690MB + 스왑
```

> 🔴 **app-01의 스왑은 2026-09-25까지 0이었다** (`#1911`). 설치 체크리스트가
> 「이미 our-tax에서 적용됐을 수 있음」으로 적혀 있었고, 실제로는 한 번도 적용되지
> 않았다. 그 상태에서 배포가 이미지 풀과 `migrate` 컨테이너를 얹자 **호스트째
> 멈췄다** — sshd가 배너조차 돌려주지 못해 배포가 `Broken pipe`로 끊기고, 터널
> 커넥터까지 죽어 API는 Cloudflare `error 1033`이 됐다. 배포가 두 번 연속 그렇게
> 실패했다. **여유는 짐작하지 말고 실측한다** — `ssh ubuntu@<app-01> 'free -m; swapon --show'`.

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
  │   ├─ 호스트 키 고정 검사 — ops/host/known_hosts 에 db-01이 없으면 여기서 멈춤 (§4.7 · #1637)
  │   ├─ git fetch <DEPLOY_SHA> + reset --hard FETCH_HEAD (~/bluelog) — 받은 커밋이 다르면 중단 (#1633)
  │   ├─ ACL 템플릿 치환 (REPLACE_ME_APP_PRIVATE_IP)
  │   ├─ .env 렌더링 (CUBRID_PASSWORD)
  │   ├─ docker compose up -d (CUBRID)
  │   ├─ 브로커 대기 (최대 120초)
  │   └─ 첫 부트 시 ALTER USER dba PASSWORD + 재시작
  │
  ├─ deploy-app (SSH → app-01)
  │   ├─ 호스트 키 고정 검사 — ops/host/known_hosts 에 app-01이 없으면 여기서 멈춤 (§4.7 · #1637)
  │   ├─ git fetch <DEPLOY_SHA> + reset --hard FETCH_HEAD (~/bluelog) — 받은 커밋이 다르면 중단 (#1633)
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
- `force_db_init` (boolean): `docker compose … down -v`로 CUBRID 데이터 볼륨을 지운
  뒤 재초기화. 실제로 지워지는 것은 명명 볼륨 `cubrid-data`가 아니라 이미지가
  선언한 익명 볼륨(`$CUBRID_DATABASES`, DB 파일이 있는 자리)이다(#1867). **데이터
  손실 비가역적** — 무손실 대안은 `docs/OPERATIONS.md §9.2` 「무손실 복구」.

#### 3.1.1 시연 동결 — `DEPLOY_FROZEN` (#789 · 결정 E-2)

**동결 시점은 10/9(금) 18:00 KST**다(2026-09-21 사용자 결정 E-1). 동결은 공지가 아니라
**워크플로가 막는다** — 머지하는 사람이 넷이라, 공지만으로 지키는 규칙은 한 사람이 몰랐을
때 깨진다.

| 할 일 | 방법 |
|---|---|
| 켜기 | GitHub → Settings → Secrets and variables → Actions → **Variables** → `DEPLOY_FROZEN` = `true` |
| 끄기 | 같은 자리에서 값을 `false`로 바꾸거나 변수를 지운다 |
| 예외 배포 | Actions → `Deploy to OCI` → **Run workflow**(수동 실행) — 동결 중에도 돈다 |

- 켜져 있으면 **push 자동 배포만** 건너뛴다. `preflight`·`deploy-frontend`가 건너뛰고,
  `build`·`deploy-db`·`deploy-app`은 `preflight`에 걸려 함께 건너뛴다. 대신 `frozen` 잡이
  「동결 중 — 건너뛰었다」 알림을 실행 기록에 남긴다.
- 변수는 코드가 아니라 저장소 설정이라 **켜고 끄는 데 재배포가 필요 없다.**
- 값은 정확히 `true`여야 동결이다(`True`·`1`은 동결이 아니다 — 워크플로가 문자열로 견준다).

### 3.2 프론트엔드 배포 (Cloudflare Pages)

**자동 (#1236)** — `deploy.yml`의 `deploy-frontend` 잡이 백엔드와 같은 push에서
빌드해 `wrangler pages deploy`로 프로덕션(`--branch main`)에 올린다. 백엔드 잡과
**독립**이다 — OCI 자격증명이 비어 있어도 화면 배포는 시도한다. 필요한 GitHub
시크릿은 `CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_ACCOUNT_ID` 둘뿐이고, 비어 있으면
잡 첫 단계에서 이름만 보고 실패한다.

수동 배포(폴백 — 자동 배포가 깨졌거나 급할 때). **자동 잡(`deploy.yml` `deploy-frontend`)과 같은 세 단계**를 손으로 한다 (`#1669`):

```bash
cd frontend
npm ci

# ⑴ 빌드 — 화면은 자기 오리진만 부른다(같은 오리진 · #1322). 상대 경로를 굳힌다
VITE_API_BASE_URL=/api/v1 npm run build

# ⑵ Pages Function이 넘길 백엔드 호스트명을 wrangler.toml에 넣는다 — 커밋하지 않는다
#    값은 시크릿 API_ORIGIN과 같다(터널 호스트명 · §3.5). ⚠️ IP를 넣으면 프록시가 403(error 1003)
sed -i 's|^API_ORIGIN = .*|API_ORIGIN = "https://<터널 호스트명>"|' wrangler.toml

# ⑶ 배포 — 출력 디렉터리와 프로젝트 이름은 wrangler.toml이 갖는다. 위치 인자(dist)를 주지 않는다
npx --yes wrangler@4 pages deploy --branch main

# 끝나면 wrangler.toml의 API_ORIGIN을 자리표시자로 되돌린다(작업 트리 변경을 버린다)
```

- **권한** — `CLOUDFLARE_API_TOKEN`(Pages:Edit)과 `CLOUDFLARE_ACCOUNT_ID`를 환경변수로 준다. 값은 GitHub 시크릿과 같다. **토큰은 문서에 적지 않는다.**
- **프로덕션과 미리보기** — `--branch main`이 프로덕션(`bluelog-bx7.pages.dev`)이다. 다른 이름을 주면 **미리보기 배포**가 되어 프로덕션 화면은 그대로다.
- **올리는 것은 작업 트리의 `dist`다** — 배포하려는 커밋을 먼저 체크아웃하고 빌드한다. 로컬에 커밋하지 않은 변경이 있으면 그대로 올라간다.
- ⚠️ **종전 이 자리의 명령**(`VITE_API_BASE_URL=http://<app-01 IP>:8001/api/v1` · `wrangler pages deploy dist --project-name bluelog`)은 **따라 하면 안 된다** — 앞의 것은 교차 사이트 쿠키가 실리지 않아 로그인이 안 되던 구성이고(`#1322`), 뒤의 것은 `wrangler.toml`의 `pages_build_output_dir`와 충돌해 wrangler가 거부한다.

Cloudflare 인증:
```bash
export CLOUDFLARE_API_TOKEN=<토큰 — 시크릿 CLOUDFLARE_API_TOKEN>
export CLOUDFLARE_ACCOUNT_ID=<계정 ID — §6.1 공개값 · 시크릿 CLOUDFLARE_ACCOUNT_ID와 같다>
```

Pages 프로젝트 정보:
| 항목 | 값 |
|------|-----|
| 프로젝트명 | `bluelog` (`frontend/wrangler.toml` `name`) |
| 프로덕션 URL | https://bluelog-bx7.pages.dev |
| 빌드 명령 | `VITE_API_BASE_URL=/api/v1 npm run build` |
| 출력 디렉토리 | `frontend/dist` (`frontend/wrangler.toml` `pages_build_output_dir`) |

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
#            OCI_DB_PRIVATE_IP=10.0.1.132   (포트 바인드 주소 · 비우면 compose가 기동을 거부한다 · #1641)

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
#   APP_ENV=staging  (현재 — 메일은 MAIL_BACKEND=smtp로 실제 발송한다 · #787)
#     production 전환은 가입 게이트(#1530)·INITIAL_ADMIN_EMAILS까지 갖춘 뒤다 (§4.5)
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

적재되는 것: 선박 **5척** · 항차 **34건**(CONFIRMED 11 · COMPLETED 1 · IN_PROGRESS 3 · PLANNED 19) · 항차 연료 34 · 정박 구간 4 · 정박 연료 8. 계정은 0행이다.

> **완료 항차 12건 중 확정 전(`COMPLETED`)은 벌크선 50k의 2026-01 항차 하나뿐이다** (#1536 · 결정요청 v6 `D-30`). 2025년 5건은 보고가 끝난 해라 전부 `CONFIRMED`이고, 2026년도 그 한 건만 빼고 `CONFIRMED`다. 그래서 데이터 점검(`UIFLOW 2-11`)은 「실적 확정 전 1건 · 이상치 1건」으로 시작하고, 둘 다 같은 항차라 「점검에서 발견 → 선박 상세에서 확정」 동선이 한 건으로 이어진다. 등급·위험 선박 서사는 확정 여부와 무관하다 — 연간 누적은 `annual_inclusion_policy`로 항차를 고른다.

**자동 배포에서는 켜지지 않는다.** `push` 트리거에는 `inputs`가 없어 빈 문자열이 되고, 셸이 `= "true"`로만 보기 때문이다. `tests/test_deploy_demo_seed.py`가 그 조건이 지워지는 것을 막는다.

#### 3.4.2 ⚠️ 시각이 적재일 기준 상대값이다 (#792)

시드의 날짜는 **적재한 날**을 기준으로 잡힌다. 진행 중 항차의 도착 예정이 `+1`~`+12`일, 관찰선의 최근 구간이 `-12`~`-8`일이다. 그래서 **적재가 오래되면 화면이 의도한 상태에서 멀어진다.**

| 경과 | 나타나는 것 |
|---|---|
| 하루 | 관찰선 진행 항차가 도착 예정을 넘겨 `IN_PROGRESS_PAST_ETA` 대상이 된다 |
| 약 3주 | 최근 구간이 30일 창을 벗어나 `NO_RECENT_DATA`가 된다 |

**적재는 덮어쓰지 않는다** — `_insert_ignoring_existing()`이 `IntegrityError`를 삼키므로 이미 있는 행은 그대로다. 다시 돌려서는 시각이 갱신되지 않고, **지우고 넣어야** 한다.

> **시연·인터뷰 직전에 `clear_demo=true` + `seed_demo=true`로 한 번 돌린다.** 회차가 여러 번이면 회차 사이에도 돌린다 — 둘러보기 세션은 관리자 권한이라 누군가 선박을 지웠을 수 있고, 다시 적재하면 되살아난다(#1486 결정).
>
> **저장한 함대 감축 계획(`fleet_reduction_plan`)은 이때 전량 지워진다** (#1536). 그 표는 시드가 넣는 것이 아니라 화면(`UIFLOW 2-10`)에서 저장한 것이라 「시드가 넣은 행」을 가려낼 표지가 없고, 삭제 API·버튼은 정본에도 없다(`API_SPEC §2.17`). 둘러보기 세션마다 누군가 계획을 저장하면 하나뿐인 시연 DB에 흔적이 쌓이므로, 재적재가 계획까지 알려진 상태로 되돌린다. 시연 DB에서 계획을 남겨야 할 이유가 생기면 재적재 전에 따로 내보낸다.
>
> **로컬 노트북은 `bash scripts/demo_up.sh --reseed`가 같은 절차다** (#1536). 4b 단계에서 `demo_seed --clear`를 돌린 뒤 적재한다. `docker compose down -v`로 대신하지 않는다 — 볼륨까지 지워 계산 이력·계정·규제 파라미터가 함께 사라진다. ⚠️ **계산 이력이 참조하는 항차·선박은 `--clear`가 남긴다**(`#1088`) — 남은 행은 적재가 덮어쓰지 않아 시각·제원이 옛 값 그대로다. `--reseed`는 그 줄(「N행 남김」)을 화면에 보이고 경고한다(`#1608`). 그 행까지 새로 잡아야 하면 그때만 `down -v`다.
>
> ⚠️ **`down`(`-v` 없이)도 사실상 같은 결과를 낸다**(#1867). CUBRID 데이터는 명명
> 볼륨이 아니라 이미지가 선언한 익명 볼륨에 있어서, `-v`가 지우는 `cubrid-data`는
> 원래 비어 있다 — 체감 결과를 가르는 것은 `-v` 유무가 아니라 **컨테이너가
> 재사용되는가**다. `down` 뒤 `up`은 그 익명 볼륨을 재사용하지 않고 새로 만들어
> 계산 이력·계정·규제 파라미터가 **똑같이** 빈 채로 뜬다(2026-09-24 로컬 실측).
> 컨테이너만 멈추고 데이터를 유지하려면 `docker compose stop`을 쓴다.

#### 3.4.3 지울 때 남는 것

`clear_demo`는 **계산 이력이 참조하는 행을 억지로 지우지 않는다**(#1088). `calculation_run`은 보존 대상이라 그것이 가리키는 항차·선박은 `RESTRICT`에 걸린다. 남긴 수는 출력에 따로 나온다.

```
fleet_reduction_plan: 2행 삭제
voyage: 34행 삭제
vessel: 5행 삭제
voyage: 0행 남김 (계산 이력이 참조)
vessel: 0행 남김 (계산 이력이 참조)
```

`fleet_reduction_plan` 행은 **남긴 수가 없다** — 시드 id로 거르지 않고 전량 지우며, 참조하는 FK가 `created_by → app_user`(`SET NULL`) 하나뿐이라 막히지 않는다(#1536).

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

서버에 접속하지 않고 밖에서 보려면 헬스 응답의 `commit`을 본다(PR #1901 · `API_SPEC §10`).
배포 워크플로도 끝에서 이 값과 배포한 커밋을 대조한다.

```bash
curl -fsS https://bluelog-bx7.pages.dev/api/v1/health | jq -r .data.commit
# → 배포 커밋(12자리) · 로컬 개발처럼 값이 없으면 null
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

#### 3.6.4 마이그레이션 `061`이 중복으로 멈추면 — 중복 정리 → upgrade 재실행 (#1631)

`061`은 `vessel.imo_active`·`app_user.email_active`(활성이면 원본의 사본 · 삭제면 NULL)에
**유니크 인덱스**를 세운다. 그 전까지 유일성은 `047`의 트리거였는데 동시 등록을 막지
못했으므로(`#1796`), 운영 DB에 **같은 IMO·이메일의 활성 행이 둘 이상** 남아 있을 수 있다.

**머지 전에 사람이 운영 DB를 조회할 필요는 없다 — 마이그레이션이 먼저 센다.** `061`은
아무것도 바꾸기 전에 두 표의 활성 중복 그룹 수를 세고, 하나라도 있으면 아래 문구의 예외로
멈춘다(G-1 결정 「다′」 · 2026-09-24). 그때 **DB는 그대로다** — `047` 트리거 4개가 남아 있고
열도 인덱스도 만들지 않았다. 배포 워크플로는 마이그레이션이 끝나야 백엔드를 올리므로(§3.1)
멈춘 동안 옛 백엔드가 옛 스키마 위에서 그대로 돈다.

```
마이그레이션 061을 적용하지 않았다 — 활성 행 안에 같은 키가 둘 이상인 그룹이 있다
(vessel.imo_number 1개 · app_user.email 0개). DB는 그대로다(047 트리거도 남아 있고
열·인덱스도 만들지 않았다). docs/OPERATIONS.md §3.6.4의 절차로 …
```

문구에는 **그룹 수만 있고 값(IMO·이메일)은 없다** — 배포 로그가 공개 저장소의 Actions에
남기 때문이다. 어느 값인지는 아래 1)에서 DB에 직접 묻는다. 마이그레이션은 **조용히 한쪽을
지우지 않는다.** 무엇을 남길지는 사람이 정한다.

```bash
# 1) 중복을 찾는다 — 활성 행끼리 같은 키 (마이그레이션 문구의 표에서만 찾으면 된다)
csql -u dba cii -c "SELECT imo_number, COUNT(*) FROM vessel WHERE is_deleted = 0 GROUP BY imo_number HAVING COUNT(*) > 1"
csql -u dba cii -c "SELECT email, COUNT(*) FROM app_user WHERE is_deleted = 0 GROUP BY email HAVING COUNT(*) > 1"

# 2) 남길 행을 정한다 — 항차·계산 이력이 달린 쪽, 로그인 이력(last_login_at)이 있는 쪽.
#    나머지는 **지우지 말고 소프트 삭제**한다(감사 로그·FK가 그 행을 참조한다 · DB_SCHEMA §7.1).
#    047의 BEFORE UPDATE 트리거는 활성 → 삭제 방향을 막지 않는다.
csql -u dba cii -c "UPDATE vessel SET is_deleted = 1 WHERE id = '<버릴 행 id>'"
csql -u dba cii -c "UPDATE app_user SET is_deleted = 1 WHERE id = '<버릴 행 id>'"

# 3) upgrade를 그대로 다시 돌린다 — 사전 검사가 0을 세면 그때 047 트리거를 걷고 열 → 백필 →
#    인덱스 → 채움 트리거 순으로 이어간다. 되돌릴 것은 없다(멈췄을 때 아무것도 바꾸지 않았다).
docker compose -f docker-compose.prod.app.yml run --rm backend alembic upgrade head
```

2)에서 소프트 삭제한 행은 백필이 `NULL`로 채워 인덱스에서 빠진다. 사전 검사가 지나간 뒤
다른 이유(연결 끊김 등)로 중간에 멈추면 각 단계가 카탈로그를 보고 이미 한 것은 건너뛰므로
같은 명령을 다시 돌리면 된다. 검사가 실제로 `047` 트리거 전에 멈추는지는
`tests/test_zz_active_key_precheck_db.py`가 CI의 CUBRID에서 확인한다.

#### 3.6.5 마이그레이션 `062`가 속력 초과로 멈추면 — 속력 정정 → upgrade 재실행 (#1269)

`062`는 속력 칸 넷(`vessel.reference_speed_kn` · `voyage.planned_speed_kn` ·
`voyage.actual_avg_speed_kn` · `voyage_scenario.speed_kn`)에 **60 kn 상한 트리거**를 건다
(`PRD §9.1` VAL-009). `BEFORE UPDATE` 트리거는 바뀌지 않은 칸도 보므로, 이미 60을 넘는 행이
있으면 **그 행의 다른 칸을 고치는 저장까지 막힌다.** 그래서 `061`과 같이 아무것도 바꾸기 전에
세고, 하나라도 있으면 칸별 행 수만 적은 문구로 멈춘다. **DB는 그대로다** — 옛 백엔드가 계속 돈다.

```bash
# 1) 어느 행인지 찾는다 — 문구에 행 수가 0이 아닌 칸만
csql -u dba cii -c "SELECT id, voyage_no, planned_speed_kn, actual_avg_speed_kn FROM voyage WHERE planned_speed_kn > 60 OR actual_avg_speed_kn > 60"
csql -u dba cii -c "SELECT id, name, reference_speed_kn FROM vessel WHERE reference_speed_kn > 60"
csql -u dba cii -c "SELECT id, voyage_id, speed_kn FROM voyage_scenario WHERE speed_kn > 60"

# 2) 바로잡는다 — 대개 자릿수 실수(12.5 → 125)다. 입력한 사람에게 맞는 값을 확인해 고친다.
#    voyage_scenario는 비교 계산이 만든 행이라 속력만 바꾸면 소요시간·연료와 어긋난다 —
#    손대기 전에 개발에 알린다(채택된 시나리오는 항차 계획과 이어져 있다).

# 3) upgrade를 그대로 다시 돌린다 — 되돌릴 것은 없다(멈췄을 때 아무것도 바꾸지 않았다).
docker compose -f docker-compose.prod.app.yml run --rm backend alembic upgrade head
```

#### 3.6.6 DB 복구(`db_backup.py restore`) — 분리 배포의 순서와 교체가 중간에 멈췄을 때 (#1635)

> 번호 — `§3.6.5`는 마이그레이션 `062`의 속력 초과 멈춤(`#1269` · PR #1890)이 쓴다.

**앱은 운영 이름의 DB가 제자리에 떠 있을 때만 켠다** — 없는 DB를 향해 켜진 앱보다 꺼진 앱이
낫다(결정 F-13). 스크립트는 교체의 어느 단계가 실패해도 아래 표대로 되돌리거나 멈추고,
어느 경우든 종료 코드 1이다.

| 실패한 단계 | 남는 상태 · 스크립트가 한 일 | 앱 |
|---|---|---|
| 대조(복구한 새 DB의 리비전·행 수·트리거) | 새 DB를 지웠다 — 운영 DB는 손대지 않았다 | 멈추지 않았다 |
| 운영 DB → 보관 이름(`cii` → `cii_b<시각>`) | 이름이 그대로다 — 운영 서버를 다시 켰다 | 켰다 |
| 새 DB → 운영 이름(`cii_s<시각>` → `cii`) | 보관 이름을 **운영 이름으로 되돌리고** 켰다. 새 DB는 `cii_s<시각>`로 남는다 | 켰다 |
| └ 되돌림도 실패 | **멈췄다.** 문구가 두 이름과 수동 명령을 준다 | **켜지 않았다** |
| 새 운영 DB 서버 기동 | **멈췄다.** 이전 운영 DB는 `cii_b<시각>`로 남는다 | **켜지 않았다** |

수동 복구(앱을 켜지 않고 멈춘 두 경우) — 문구가 준 이름 그대로 친다.

```bash
# 되돌림이 실패했을 때 — 이전 운영 DB를 제 이름으로
cubrid renamedb cii_b<시각> cii && cubrid server start cii
# 새 운영 DB가 켜지지 않았을 때 — 새 DB를 비키고 이전 운영 DB를 제 이름으로
cubrid renamedb cii cii_s<시각> && cubrid renamedb cii_b<시각> cii && cubrid server start cii
# 그다음 앱을 켠다(단일 호스트: docker compose start app · 분리 배포: 아래 5))
```

**분리 배포(db-01 · app-01)** — db-01에는 앱 서비스가 없다. 스크립트는 다른 호스트를 다루지
않고(결정 F-13 「가」), 운영자가 앱을 멈추고 켠다. `APP_SERVICE=none`이면 스크립트가 앱을
건드리지 않으며, **`--app-stopped` 없이는 교체를 시작하지 않는다.**

```bash
# 1) db-01 — 백업과 리허설
export COMPOSE="docker compose -f docker-compose.prod.db.yml" DB_SERVICE=cubrid APP_SERVICE=none
python3 scripts/db_backup.py backup
python3 scripts/db_backup.py rehearse backups/<파일>.dump
# 2) app-01 — 앱을 멈춘다
docker compose -f docker-compose.prod.app.yml stop backend
# 3) db-01 — 교체(앱을 멈췄다고 적는다)
python3 scripts/db_backup.py restore backups/<파일>.dump --confirm cii --app-stopped
# 4) 3)이 「복구 완료」면 app-01에서 앱을 켠다. 실패 문구가 「앱을 켜지 않았습니다」면 켜지 말고
#    위 수동 복구부터
docker compose -f docker-compose.prod.app.yml up -d backend
# 5) 헬스
curl -fsS http://127.0.0.1:8001/api/v1/health
```

⚠️ **「살아 있는 접속이 있으면 거부」를 하지 않는 이유** — 결정 F-13은 그것을 적었으나 실측상
판정 수단이 없다. db-01 브로커의 CAS가 앱이 끊긴 뒤에도 DB 연결을 붙잡고 있어
(`cubrid tranlist` — 앱 중지 직후 `ACTIVE` 9 · 80초 뒤 5 · 2026-09-25 로컬) 앱 접속과 구별되지
않는다. 그래서 운영자가 2)를 했다는 것을 `--app-stopped`로 명시하게 했다. 실서버 리허설
1회(`#788`·`#789`)는 사람이 이 순서를 한 번 밟아 본다.

---

## 4. 보안

### 4.1 DB 접근 4층 방어

```
외부 → OCI Security List(1층) → 바인드 주소(2층) → CUBRID broker ACL(3층) → CUBRID server ACL(4층)
```

| 층 | 위치 | 설정 파일/도구 | 허용 대상 |
|----|------|---------------|-----------|
| 1 | OCI Security List | OCI 콘솔 | 10.0.0.0/16 → :33100 |
| 2 | 바인드 주소 (db-01 사설 IP에만 게시) | `docker-compose.prod.db.yml` `ports` — `${OCI_DB_PRIVATE_IP}:33100:33000` | 10.0.1.132:33100 소켓만 열린다. 공용 IP(132.226.170.195)에는 소켓이 없다 |
| 3 | CUBRID broker ACL | `ops/cubrid/conf/broker_access.conf` | cii:dba:10.0.1.216 |
| 4 | CUBRID server ACL | `ops/cubrid/conf/server_access.conf` | 127.0.0.1, 172.* |

> **[#1641] 2층은 ufw가 아니다 — ufw는 이 포트에 관여하지 않는다.** 종전 표는 2층을 `db-01 ufw`(`ufw allow from 10.0.1.216 to any port 33100`)로 적었다. 그런데 Docker가 publish한 포트로 오는 패킷은 DNAT 뒤 **FORWARD 체인**(`DOCKER-USER` → `DOCKER`)으로 흐르고 호스트의 **INPUT 체인을 거치지 않는다**([Docker Docs — Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)). ufw의 `allow`·`deny`는 INPUT 규칙이므로 그 트래픽을 본 적이 없다 — **규칙이 있어도 막지 못했고, 없어도 열리지 않는다.** 즉 종전 구성은 「모든 인터페이스에 열려 있고 2층이 없는」 상태였다(실제 노출은 1층 Security List가 막고 있었다).
>
> 그래서 소켓 자체를 사설 인터페이스에만 둔다. `deploy.yml`의 `deploy-db`가 시크릿 `OCI_DB_PRIVATE_IP`를 db-01 `.env`에 렌더하고 compose가 그 주소로 게시한다. 값이 비면 compose가 기동을 거부한다(`:?` — 비면 `:33100:33000`이 되어 다시 모든 인터페이스로 열리기 때문). 배포는 `up -d` 직후 `docker compose port cubrid 33000`이 `<사설 IP>:33100`인지 확인하고 아니면 멈춘다 — 재배포마다 컨테이너가 다시 만들어지므로 그때마다 본다. app-01은 이미 사설 IP로 붙고(`CUBRID_HOST=${OCI_DB_PRIVATE_IP}`), `db_backup.py`·`purge_expired.py`는 `docker compose exec`라 포트를 쓰지 않는다. **ufw를 켜는 것은 별개 사안이다** — SSH만 다루며 ourtax와 공유하는 호스트라 호스트 소유자 확인이 먼저다(§10.4).
>
> **적용 뒤 실측** — ⚠️ 아래는 **아직 실측하지 않았다**(2026-09-24 · 서버 앞에서 사람이 한 번 확인한다).
>
> ```bash
> # db-01에서 — 사설 IP 한 줄만 보여야 한다. 0.0.0.0이나 [::]가 보이면 되돌아간 것이다
> ss -ltnp 'sport = :33100'
> docker compose -f ~/bluelog/docker-compose.prod.db.yml port cubrid 33000   # → 10.0.1.132:33100
>
> # 외부(사용자 노트북 · 공인 IP)에서 — 소켓이 없으므로 1층이 막든 아니든 붙지 않는다
> nc -vz -w 5 132.226.170.195 33100          # 기대: 시간 초과 또는 거부
>
> # app-01에서 — 허용 경로는 그대로 붙는다
> nc -vz -w 3 10.0.1.132 33100               # 기대: succeeded
> ```

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
| `staging` | 배포 검증 · **현재 클라우드 배포** | `console` 허용 · `smtp`면 실제 발송 | 비활성 | **닫힘** (#1058) |
| `production` | 운영 | `smtp` 필수 (console이면 기동 실패) | 필수 | **닫힘** |

현재 상태: **`staging` + `MAIL_BACKEND=smtp`** — 인증·재설정 메일이 **실제로 발송된다** (2026-09-21 · `#787`).

- **메일을 켜는 데 `production`이 필요하지 않다.** `mail/config.py`가 막는 것은 「`production`인데 `console`」 한 조합뿐이고, `smtp` 분기는 `APP_ENV`를 보지 않는다. 시크릿 6종(§5.2)만으로 `staging`에서 실제 발송한다.
- **`production` 전환은 아직이다.** 바꾸면 기동 가드 셋이 함께 돈다 — 메일(`#524`, 지금은 통과) · 가입 게이트(`#808` — 시크릿이 비어 있으면 거부 · `#1530`) · 최초 관리자(`INITIAL_ADMIN_EMAILS` — 비어 있으면 거부). 뒤의 둘을 갖춘 뒤 바꾼다.

> ⚠️ **기동은 SMTP에 접속해 보지 않는다** (`api/main.py` lifespan — 설정만 읽는다). 앱 비밀번호가 틀려도 배포·`/health`는 초록불이고, 틀린 것은 **첫 발송에서** 드러난다 — 가입은 발송이 실패해도 `201`로 끝나고 로그에만 남으며(`routes/auth.py` `가입 확인 메일 발송 실패 — 계정은 생성됨`), 인증 메일 재발송·비밀번호 재설정은 `500`(「메일이 발송되지 않았습니다」)을 낸다. 배포 로그의 `메일 백엔드: smtp`는 **설정을 읽었다**는 뜻일 뿐이다. SMTP 시크릿을 바꾸면 **실제 수신함으로 왕복**해 확인한다.

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

### 4.7 배포 SSH 호스트 키 고정 (#1637)

배포 워크플로는 **실행 중에 호스트 키를 받지 않는다.** 종전에는 배포 직전에 `ssh-keyscan`으로 원격 호스트의 공개키를 받아 `known_hosts`에 넣었는데, 그러면 네트워크 경로에서 잘못된 키가 주입돼도 같은 연결 흐름이 그 키를 믿게 되어 호스트 신원 검증이 있으나 마나였다.

지금은 사람이 지문을 대조해 커밋한 저장소 파일 **`ops/host/known_hosts`** 를 워크플로가 `~/.ssh/known_hosts`로 복사(덮어쓰기)한 뒤 `ssh -o StrictHostKeyChecking=yes`로 접속한다. 키가 어디서 왔고 언제 바뀌었는지가 PR 이력으로 남고, `tests/test_deploy_host_key_pinning.py`가 `ssh-keyscan`이 되살아나지 않는지·엄격 검사가 붙어 있는지·파일의 줄이 ssh가 읽을 수 있는 모양인지를 CI에서 본다.

> **시크릿에 넣지 않는 이유** — 시크릿은 값이 보이지 않아 잘못 넣어도 PR에서 잡히지 않고, 바꾼 이력도 남지 않는다. 호스트 공개키는 감출 것이 아니라 **대조할 것**이다. 공용 IP는 이 문서 §5.1에 이미 적혀 있으므로 파일에 그대로 둔다(해시하지 않는다 — 리뷰에서 어느 호스트의 줄인지 봐야 한다).

#### 파일 형식

한 호스트당 한 줄. `#`로 시작하는 줄은 주석이다.

```
132.226.170.195 ssh-ed25519 AAAA…   ← db-01 (OCI_DB_HOST)
131.186.22.10 ssh-ed25519 AAAA…     ← app-01 (OCI_APP_HOST)
```

#### 최초 확보 — 두 경로에서 얻은 지문이 같아야 넣는다

배포 경로 하나에서만 받은 값을 넣으면 종전과 다를 것이 없다. 그래서 **서버 자신이 말하는 지문**과 **밖에서 받은 줄의 지문**을 따로 얻어 대조한다. 호스트마다 반복한다.

1. 서버 콘솔에서 지문을 읽는다 — OCI 콘솔의 시리얼 콘솔이나 이미 신뢰된 SSH 세션에서 실행한다.

   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   # 256 SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx root@db-01 (ED25519)
   ```

2. 다른 경로(자기 PC)에서 `known_hosts` 줄을 받고, 그 줄의 지문을 계산한다.

   ```bash
   ssh-keyscan -t ed25519 132.226.170.195 2>/dev/null | tee /tmp/db-01.line | ssh-keygen -lf -
   # 256 SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx 132.226.170.195 (ED25519)
   ```

3. 두 `SHA256:…` 이 **글자 하나까지 같으면** `/tmp/db-01.line`의 줄을 `ops/host/known_hosts`에 넣는다. 다르면 넣지 않고 원인을 찾는다 — 경로 어딘가에서 키가 바뀌고 있다는 뜻이다.

4. app-01(`131.186.22.10`)도 같은 순서로 한다.

5. 넣은 파일을 로컬에서 확인한다.

   ```bash
   ssh-keygen -lf ops/host/known_hosts                     # 두 줄의 지문이 1번과 같은가
   ssh-keygen -F 132.226.170.195 -f ops/host/known_hosts   # 워크플로가 하는 검사와 같다 — 0이면 있음
   ssh-keygen -F 131.186.22.10 -f ops/host/known_hosts
   ```

6. PR을 올린다. **PR 본문에 1번과 2번의 지문을 적는다** — 리뷰어가 대조한 사실이 이력에 남는다. 머지 즉시 배포가 도므로 첫 머지는 낮에 하고 `gh run watch`로 `SSH 설정` 단계가 지나가는지 본다.

#### 실패 동작 — 어느 경우든 원격 명령은 돌지 않는다

| 상황 | 어디서 서나 | 로그에 보이는 것 | 서비스 |
|---|---|---|---|
| 파일에 그 호스트 줄이 없다 | `SSH 설정` 단계 (`ssh-keygen -F` 가 1로 끝난다) | `::error::ops/host/known_hosts 에 db-01(OCI_DB_HOST)의 호스트 키가 없다` | 이전 컨테이너가 그대로 돈다 |
| 줄은 있는데 서버의 키와 다르다 — 서버 재설치 · 호스트 키 교체 · 중간자 | `ssh` 접속 (종료 코드 255) | `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` … `Host key verification failed.` | 이전 컨테이너가 그대로 돈다 |

두 경우 모두 **개인키·`CUBRID_PASSWORD`·`GITHUB_TOKEN`은 로그에 나오지 않는다.** 멈추는 메시지는 시크릿 **이름**만 적고, ssh는 원격 명령 문자열을 오류에 싣지 않으며, GitHub Actions는 시크릿 값이 출력에 섞이면 `***`로 가린다. `tests/test_deploy_host_key_pinning.py::test_the_failure_path_prints_no_secret`가 메시지 줄에 시크릿 참조가 없는지 본다.

#### 키 교체 — 호스트 키가 바뀌었을 때

OS 재설치나 `ssh-keygen -A` 로 서버의 호스트 키가 바뀌면 배포가 위 표의 둘째 줄로 선다. 그때는:

1. **왜 바뀌었는지 먼저 확인한다.** 사람이 서버를 다시 만든 것이 아니라면 넣지 않는다 — 경고가 말하는 그대로 누군가 중간에 끼어들었을 수 있다.
2. 위 「최초 확보」 1~5번을 그 호스트에 대해 다시 한다. 옛 줄은 지운다(같은 호스트에 두 줄을 두면 ssh가 어느 쪽을 볼지 사람이 읽기 어렵다).
3. PR 본문에 바뀐 사유와 두 경로의 지문을 적고 리뷰를 받은 뒤 머지한다. 머지가 곧 배포이므로 `gh run watch`로 확인한다.

> **수동 SSH(§3.3)에는 적용되지 않는다.** 이 절은 GitHub Actions 러너의 `known_hosts`에 관한 것이다. 자기 PC의 `~/.ssh/known_hosts`는 첫 접속 때 저장한 키를 계속 쓰며, 서버 키가 바뀌면 같은 경고를 낸다 — 그때도 위 1번대로 콘솔에서 지문을 확인한 뒤에 옛 줄을 지운다.

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
| `OCI_DB_PRIVATE_IP` | db-01 VCN 사설 IP (app-01의 DATABASE_URL · **db-01의 CUBRID 포트 바인드 주소** — `#1641`) | `10.0.1.132` |
| `OCI_APP_PRIVATE_IP` | app-01 VCN 사설 IP (ACL 치환) | `10.0.1.216` |
| `CUBRID_PASSWORD` | dba 비밀번호 (<=31바이트, ASCII) | |
| `CORS_ALLOW_ORIGINS` | 프론트엔드 오리진 | `https://bluelog-bx7.pages.dev` |
| `APP_PUBLIC_URL` | 메일 링크 기준 주소 | `https://bluelog-bx7.pages.dev` |
| `INITIAL_ADMIN_EMAILS` | **최초 관리자** 이메일(쉼표 구분). 여기 든 주소는 **가입·로그인할 때마다** 관리자로 맞춰진다 — 「처음 한 번」이 아니라 「항상 관리자인 사람」이다. ⚠️ **비면 관리자 0명으로 뜨고 화면으로는 아무도 역할을 올릴 수 없다** (`#672` · `#1301`). `APP_ENV=production`이면 기동이 거부되지만 **`staging`에는 그 가드가 없어 조용히 뜬다** — 배포 기본값이 `staging`이므로(`#1478`) **반드시 등록한다** (`#1475`) | `a@ex.com,b@ex.com` |
| `CLOUDFLARE_API_TOKEN` | **Cloudflare Pages 배포 토큰**(Pages:Edit). 없으면 `deploy-frontend`가 자격증명 점검에서 멈춰 **화면이 영원히 옛 판**으로 남는다 — 실제로 8회 연속 실패했다 (`#1236` · `#1479`) | |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare 계정 ID (§6.1 공개값) | `22abb4f21a4c7886292a2a0ecadf331b` |
| `API_ORIGIN` | Pages Function이 백엔드를 부를 **호스트명**(`https://` 포함 · §3.5). ⚠️ **IP를 넣으면 프록시가 403(`error 1003`)을 낸다** — Workers는 IP로 요청하지 못한다 (`#1496`) | `https://bluelog-api.kpubdata.com` |
| `PROXY_CLIENT_IP_SECRET` | **프록시 서명 헤더의 비밀 값**(`#1483`). 배포가 Pages 시크릿과 app-01 `.env`에 **같은 값**을 넣는다. 프록시가 원 클라이언트 IP를 이 값과 함께 실어 보내고, 백엔드 요청 한도는 값이 맞을 때만 그 IP로 센다(§1.2). ⚠️ 없으면 `deploy-frontend`가 **의도적으로 멈춘다** — 비어도 요청은 통하지만 현장 전원이 로그인 10회/분을 나눠 쓰는 상태로 조용히 돌아가기 때문이다. 값은 난수(`openssl rand -hex 32`) | |

> **위 넷은 「필수」의 뜻이 서로 다르다.** 앞의 9종이 없으면 **백엔드 배포**가 서고, `CLOUDFLARE_*`·`API_ORIGIN`·`PROXY_CLIENT_IP_SECRET`이 없으면 **화면 배포**가 선다. 잡이 갈라져 있어 한쪽이 빨간불이어도 다른 쪽은 초록불이므로, **`Deploy to OCI` 실행의 5잡이 모두 초록불인지**로 확인한다 (`#1201` · `#1479` · `#1496`이 전부 이 자리에서 났다).

### 5.2 권장 시크릿

| 시크릿 | 설명 |
|--------|------|
| `SIGNUP_ALLOWED_DOMAINS` | 가입 허용 메일 도메인 (쉼표 구분) |
| `SIGNUP_INVITE_CODE` | 초대 코드 (16자 이상 권장). 문자 집합 주의는 아래 `TOUR_ACCESS_CODE` 행과 같다 — 모든 시크릿에 해당한다 |
| `MAIL_BACKEND` | `smtp`. **등록됨(2026-09-21 · `#787`)** — `staging`에서도 실제 발송한다(§4.5). 비우면 `console`(로그로만) |
| `MAIL_FROM` | 발신 주소. 현재 `BlueLog <26hp043@gmail.com>`. ⚠️ **Gmail SMTP는 `SMTP_USER` 계정 주소로 둔다** — 다른 주소를 넣으면 Gmail이 계정 주소로 덮어쓴다(별칭 등록 주소 제외). **비우면 `BlueLog <no-reply@localhost>`로 나간다** |
| `SMTP_HOST` | SMTP 서버 (예: `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP 포트. **비워 두면 587**(submission)이다. **465를 넣으면 implicit TLS**로 붙는다 — 연결하는 순간부터 TLS이고 `SMTP_USE_TLS`와 무관하게 STARTTLS를 걸지 않는다(`RFC 8314 §3.3` · `#1331`) |
| `SMTP_USER` | SMTP 사용자 |
| `SMTP_PASSWORD` | SMTP 비밀번호. Gmail은 계정 비밀번호가 아니라 **앱 비밀번호**(16자, 계정 2단계 인증이 켜져 있어야 발급된다 · myaccount.google.com/apppasswords)다. 공용 계정 `26hp043@gmail.com`에서 발급한다. 계정 비밀번호를 바꾸면 무효가 될 수 있으니, 그때는 재발급해 이 시크릿을 갈고 재배포한다 |
| `SMTP_USE_TLS` | STARTTLS 사용 여부. 비워 두면 `true`. `SMTP_PORT=465`(implicit TLS)에서는 값과 무관하다 (`#1475`에서 배선) |
| `TOUR_ACCESS_CODE` | **둘러보기 링크의 접근 코드** (`#1486`). `/login?tour=<코드>`로 들어온 사람에게 관리자 열람 세션을 준다. ⚠️ **비면 둘러보기가 닫힌다**(fail-closed) — 가입 게이트와 반대 방향이라 미설정이 안전한 기본값이다. 코드는 URL에 실려 브라우저 히스토리·접근 로그에 남으므로 **32자 이상**을 권하고, 인터뷰가 끝나면 비운다. 다만 **이미 발급된 세션은 7일간 살아 있다**. ⚠️ **문자는 `[A-Za-z0-9_-]`로 한정한다**(`python -c "import secrets;print(secrets.token_urlsafe(32))"`) — `'`가 들어가면 배포 ssh 인용이 끊겨 **잡이 통째로 실패**하고, `$`가 들어가면 compose가 `.env`를 보간해 **값이 조용히 잘린다**(`#1495` 실측). 잘려도 fail-closed라 링크만 거절되지만 원인이 보이지 않는다 |

### 5.3 선택 시크릿

| 시크릿 | 설명 |
|--------|------|
| `APP_ENV` | 배포 환경. **비워 두면 `staging`** (`#524` — SMTP 미설정 배포의 정상 경로 · §4.5). `SMTP_*`를 등록한 뒤 `production`으로 바꾼다. 비워 둔 채로도 `deploy.yml`이 `.env`에 `APP_ENV=staging`을 렌더링하므로 compose 기본값(`production`)으로 떨어지지 않는다 (`#1201`). |
| `CLOUDFLARE_TUNNEL_TOKEN` | 🔴 **비워 둔다 (의도).** 터널 커넥터는 app-01의 **systemd `cloudflared`**가 이미 제공하며 `ourtax`와 공유한다(§3.5). 등록하면 compose가 커넥터를 **하나 더** 띄운다. 배포 로그의 `::warning:: CLOUDFLARE_TUNNEL_TOKEN 미설정`은 **정상 상태의 표시**다 |
| `TOUR_PUBLIC` | **코드 없이 둘러보기를 여는 스위치**(`true`일 때만 열림 · `#1486` 후속). 켜면 로그인 화면에 「로그인 없이 둘러보기」 버튼이 상시 노출되고 접근 코드 없이 들어온다. ⚠️ **접근 코드를 `VITE_`로 넣지 않는다** — 빌드 산출물에 그대로 인라인되어 비밀 링크보다 못해진다. 화면에는 이 **불리언만** 전달된다(`VITE_TOUR_PUBLIC`). 문이 넓어져도 권한은 그대로다 — 둘러보기 세션은 **읽기 전용**이다(§3.7) |
| `LLM_API_KEY` | 챗봇 LLM API 키. **비어 있거나 자리표시자 `-`면 챗봇만 비활성**(`#1535`) — 화면은 패널을 열 때 `GET /chat/status`로 먼저 안다(`API_SPEC §15.7`). 켜졌는지는 로그인한 브라우저에서 그 주소를 열어 `available`로 확인한다 |
| `DATA_GO_KR_SERVICE_KEY` | **공공데이터포털 인증키**(`#1197` · 2026-09-23 등록 · 개인 계정 자동승인 · 세 API 공용). 해양수산부 선박운항정보(`VsslEtrynd5/Info5`)로 공적 재항 기록을 받는다. **비우면 수집 경로만 꺼진다** — 화면·계산은 그대로다. 키는 64자 영숫자라 Encoding·Decoding 구분이 없다. 개발계정 하루 10,000건 · **수집**: `docker compose exec -T backend python -m cii_platform.port_calls.collect`(기본 최근 400일 · 11개 항만청 · 호출부호가 있는 선박만 · `--call-sign`·`--authority`·`--start`·`--end`) → `port_call_record`(`DB_SCHEMA §2.25`). 한 (선박, 항만청)의 실패는 그 쌍만 건너뛰고 종료 코드 1 |
| `LLM_BASE_URL` | 챗봇 연결의 기준 주소(`#1535`). **비우면 `https://api.anthropic.com`**. 경로 `/v1/messages`는 코드가 붙인다. Anthropic Messages 형식을 내는 다른 공급자로 옮길 때만 넣는다 |
| `LLM_MODEL` | 챗봇 모델 이름(`#1535`). **비우면 `claude-haiku-4-5-20251001`** |
| `LLM_AUTH_SCHEME` | 챗봇 인증 헤더 방식(`#1535`). **비우면 `x-api-key`**, 다른 값은 `bearer`(`Authorization: Bearer`) 하나다. ⚠️ **그 밖의 값이면 챗봇이 꺼진다** — 운영자가 적은 것과 다른 헤더로 키를 내보내지 않기 위해서다 |

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

**§3.2 「수동 배포」와 같다** — 명령을 두 곳에 적지 않는다(`#1669`). 종전 이 절은 §3.2와 같은 낡은 명령(`VITE_API_BASE_URL=http://<IP>…` · 위치 인자 `dist`)을 한 벌 더 들고 있었다.

### 6.3 커스텀 도메인 추가 (향후)

```bash
wrangler pages project add-domain bluelog <도메인>
```

도메인 추가 시 변경 필요:
1. 백엔드 `CORS_ALLOW_ORIGINS`에 새 도메인 추가
2. 프론트엔드 빌드는 `VITE_API_BASE_URL=/api/v1` 그대로다(같은 오리진) — 백엔드 호스트명은 시크릿 `API_ORIGIN`이 정한다
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
  │       ├── known_hosts            # 배포 SSH 호스트 키 고정 — 사람이 지문 대조 후 커밋 (§4.7 · #1637)
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
`request_id`·`method`·`path`·`status`·`duration_ms`·`client`·`peer`를 더 싣는다(`client`는 요청 한도와 같은 규칙으로 판정한 IP, `peer`는 소켓 상대 — §1.2.1). 예외 기록은
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

# CUBRID DB 디렉터리 (db-01) -- 보관 로그(archive log)를 포함한 실제 사용량 (#1640).
# 데이터는 이미지의 $CUBRID_DATABASES(/home/cubrid/CUBRID/databases)에 있다 -- /var/lib/cubrid가 아니다.
# 복구는 보관 로그가 아니라 논리 덤프로 한다(scripts/db_backup.py · §3.6.3의 1)·3)) -- 이 값이 커져도 복구 절차는 같다.
ssh -i ~/.ssh/oci_ourtax_vm ubuntu@132.226.170.195 \
  "docker exec cii-cubrid sh -c 'du -sh \"\$CUBRID_DATABASES/cii\"'"
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

원인 후보가 둘이다 — 순서대로 확인한다.

1. **호스트명 불일치** — CUBRID가 `databases.txt`에 기록한 호스트명과 현재 컨테이너
   호스트명이 다르다.
2. **빈 DB로 떴다**(#1867) — **§9.2.1로 옮기기 전의 호스트**에서는 실제 DB 데이터가
   명명 볼륨 `cubrid-data`(`/var/lib/cubrid`에 붙어 비어 있었다)가 아니라 이미지가 선언한
   익명 볼륨(`$CUBRID_DATABASES` = `/home/cubrid/CUBRID/databases`)에 있다.
   `docker compose down`은 `-v` 없이도 다음 `up`에서 그 익명 볼륨을 재사용하지 않고
   **새로** 만든다. 새 볼륨에는 `databases.txt`조차 없어 컨테이너 진입점이 `cii`를 다시
   초기화하고, 옛 호스트명으로 접속하던 클라이언트가 이 오류를 본다(2026-09-24 로컬 실측).
   옮긴 뒤에는 `cubrid-data`가 데이터 경로에 붙어 `down` 뒤에도 같은 볼륨이다.

확인:
```bash
# 경로는 $CUBRID_DATABASES다 — /var/lib/cubrid 쪽이 아니다(거기는 원래 비어 있다).
docker exec cii-cubrid cat "$CUBRID_DATABASES/databases.txt"
```

`hostname: cii-cubrid`이 docker-compose.prod.db.yml에 고정되어 있는지 확인한다.
고정돼 있는데도 이 오류가 나면 2번(빈 DB로 뜸)일 가능성이 높다 — 용량을 함께
확인한다(정상은 수백 M, 방금 새로 뜬 빈 DB는 수십 K다).

```bash
docker exec cii-cubrid sh -c 'du -sh "$CUBRID_DATABASES"'
```

#### 무손실 복구 — 옛 익명 볼륨을 다시 붙인다

`down`(`-v` 없이)이 만든 새 익명 볼륨은 옛 볼륨을 지우지 않는다. 옛 볼륨은
**고아로 남아 있을 뿐**이라 데이터가 사라진 것이 아니라 가려진 것이다 — 아래
순서로 되찾는다. **`docker volume prune`·`docker system prune --volumes`는 쓰지
않는다** — 고아 볼륨이 그 명령의 대상이라 복구 가능성이 통째로 사라진다(비가역).

```bash
# 1. 고아 볼륨 찾기 — 생성 시각이 문제가 생긴 시점 근처인 익명 볼륨을 고른다
#    (com.docker.volume.anonymous 라벨이 있고 이름이 cubrid-data가 아닌 것)
docker volume ls --format '{{.Name}}\t{{.CreatedAt}}'

# 2. 후보 볼륨의 내용을 읽기 전용으로 확인한다 (databases.txt · 용량)
docker run --rm -v <volume-id>:/old:ro cubrid/cubrid:11.4 \
  sh -c 'cat /old/databases.txt; du -sh /old'

# 3. 맞으면 그 볼륨을 $CUBRID_DATABASES 자리에 다시 붙여 올린다 — 임시 override로
#    그 익명 볼륨을 외부(named) 볼륨처럼 지정한다
cat > docker-compose.recover.yml <<'EOF'
services:
  cubrid:
    volumes:
      - recovered-db:/home/cubrid/CUBRID/databases
volumes:
  recovered-db:
    external: true
    name: <volume-id>
EOF
docker compose -f docker-compose.prod.db.yml -f docker-compose.recover.yml \
  up -d --force-recreate

# 4. 행 수 등으로 정상 복구를 확인한 뒤 docker-compose.recover.yml을 지운다
#    (repo에 커밋하지 않는 임시 파일이다)
rm docker-compose.recover.yml
```

옛 볼륨이 없거나(이미 지워졌거나) 내용을 신뢰할 수 없을 때만 `force_db_init`으로
재생성한다(**데이터 손실 비가역적** — §3.1 「수동 트리거」 참고).

#### 9.2.1 이름 있는 볼륨으로 옮기기 — 호스트마다 한 번 (#1867)

compose가 `cubrid-data`를 이미지의 데이터 경로(`/home/cubrid/CUBRID/databases`)에 붙인
뒤로, **아직 옛 익명 볼륨에 데이터가 있는 호스트**는 한 번 옮겨야 한다. 옮기지 않고 새
compose로 올리면 빈 `cubrid-data`가 데이터 경로를 덮어 **DB가 빈 것처럼 보인다**(데이터는
옛 익명 볼륨에 그대로 남아 되돌릴 수 있다). 그래서 배포 DB 단계가 `up -d` 전에
「데이터 경로가 익명 볼륨인데 `cubrid-data`에 `cii/`가 없다」를 보고 **멈춘다** — 컨테이너를
건드리기 전이라 서비스는 그대로다.

**운영(db-01) — 낮에, 사람이 지켜볼 때.** `cii-cubrid`만 멈춘다. `ourtax-cubrid`는 건드리지
않는다(§2 · 같은 VM). 앱 중단은 리허설 기준 수 분이다(복사 시간은 데이터 크기에 비례한다).

```bash
# 0) 디스크 여유 — 복사본이 원본보다 커질 수 있다(리허설: 원본 775M → 복사본 1.3G.
#    CUBRID가 미리 잡아 둔 희소 파일이 복사에서 풀린 것으로 보인다 · 정황). 여유가
#    원본의 두 배 미만이면 멈추고 알린다 — VM이 1GB 메모리·작은 디스크다.
df -h /var/lib/docker
docker exec cii-cubrid sh -c 'du -sh "$CUBRID_DATABASES"'

# 1) 백업 — 이후 모든 단계의 안전망이다(#788). 매니페스트의 table_counts가 대조 기준.
#    db-01은 분리 토폴로지라 compose 파일과 서비스 이름을 준다(기본값은 단일 호스트용)
export COMPOSE="docker compose -f docker-compose.prod.db.yml" DB_SERVICE=cubrid
python3 scripts/db_backup.py backup

# 2) 앱 정지(app-01) → DB 정지(db-01). 쓰는 도중에 복사하면 파일 일관성이 깨질 수 있다
docker compose -f docker-compose.prod.app.yml stop backend        # app-01
docker compose -f docker-compose.prod.db.yml stop cubrid          # db-01

# 3) 옛 익명 볼륨 → cubrid-data 복사 (db-01). 옛 볼륨은 지우지 않는다 — 되돌릴 자리다
ANON=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/home/cubrid/CUBRID/databases"}}{{.Name}}{{end}}{{end}}' cii-cubrid)
NAMED=$(docker volume ls -q --filter label=com.docker.compose.project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' cii-cubrid) --filter label=com.docker.compose.volume=cubrid-data)
echo "익명=$ANON · 이름=$NAMED"          # 둘 다 비어 있지 않아야 한다
docker run --rm -v "$ANON":/from:ro -v "$NAMED":/to --entrypoint sh cubrid/cubrid:11.4 -c 'cp -a /from/. /to/ && ls /to'

# 4) 새 compose를 배포한다 — 이 변경(#1867 PR)의 머지가 곧 이 단계다. 사전 검사가
#    `cubrid-data`에 `cii/`가 있는 것을 보고 통과하고, `up -d`가 새 마운트로 컨테이너를
#    다시 만든다. 앱 단계가 이어서 백엔드를 올린다

# 5) 확인 — 마운트와 행 수
docker inspect -f '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{println}}{{end}}' cii-cubrid
#    → <프로젝트>_cubrid-data -> /home/cubrid/CUBRID/databases 이어야 한다
#    표별 행 수를 1)의 매니페스트 table_counts와 대조한다. 1)이 남긴 DB_BACKUP 감사 행
#    하나만큼 audit_log가 +1인 것은 정상이다(백업이 행 수를 센 뒤 감사 기록을 남긴다)

# 6) 다시 백업 — 「옮긴 뒤의 알려진 좋은 상태」 (1)의 COMPOSE·DB_SERVICE 그대로)
python3 scripts/db_backup.py backup
```

**되돌리기** — 5)에서 행 수가 다르거나 빈 DB로 보이면, 옛 익명 볼륨이 그대로 있으므로
이 변경을 되돌리는 PR을 배포하면 옛 마운트(`/var/lib/cubrid`)로 돌아가 옛 익명 볼륨을 다시
쓴다 — 그 전에 옛 볼륨이 붙지 않으면 §9.2 「무손실 복구」로 `$ANON`을 다시 붙인다.
`docker volume prune`은 쓰지 않는다.

**로컬 개발 스택** — `docker-compose.yml`도 같은 마운트다. 이 변경 뒤 처음 `up`하면
`cii`·`cii_test`가 빈 채로 보인다. 위 2)~3)을 컨테이너 이름만 같게(`cii-cubrid`) 돌려 옮기거나,
옮기지 않고 다시 적재한다(`scripts/demo_up.sh` · 테스트 DB는 `cii_test` 재생성).

**리허설 (2026-09-25 01시 · 로컬 일회용 compose `rh1867` · 운영 compose의 옛 마운트 복제)** —
head `061`까지 마이그레이션 + 규제·데모 시드 + 시험 표 1,000행(27표 · 1,150행) →
`db_backup.py backup` → 정지 → 복사 → 새 마운트로 기동: **27표 모두 행 수 같음**(차이는
백업이 남긴 `DB_BACKUP` 감사 행 1) → **`down` → `up` 뒤에도 같음**(옛 마운트에서는 이 단계가
빈 DB였다). 배포 사전 검사는 세 상태에서 돌렸다 — 옮긴 뒤 통과 · 옛 마운트에 `cubrid-data`
빔 → **exit 1** · 옛 마운트에 복사까지 마침 → 통과.

### 9.3 app-01에서 db-01 연결 실패

```bash
# 1. 네트워크 연결 확인
ssh ubuntu@131.186.22.10 "nc -vz 10.0.1.132 33100 -w 3"

# 2. 실패 시: OCI Security List에 33100이 있는지 확인
# OCI 콘솔 → Networking → Virtual Cloud Networks → ourtax-vcn → Security Lists

# 3. db-01의 CUBRID 게시 주소 확인 — 사설 IP(10.0.1.132:33100)여야 한다 (#1641 · ufw는 이 포트에 관여하지 않는다)
ssh ubuntu@132.226.170.195 "ss -ltn 'sport = :33100'"

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
swapon --show      # 비어 있으면 스왑이 없다 — 아래를 돌린다 (#1911)
docker stats --no-stream

# 스왑 설정 (멱등 · 재부팅을 견디는 /swapfile을 만든다)
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
- [x] ~~**SMTP 설정**~~ — 완료(2026-09-21 · `#787`). 공용 계정 Gmail SMTP(587 · STARTTLS), `staging`에서 실제 발송(§4.5)
- [ ] **`APP_ENV=production` 전환** — 가입 게이트 시크릿(`#1530`) · `INITIAL_ADMIN_EMAILS`를 갖춘 뒤(§4.5)
- [x] ~~**GitHub Secrets 등록**~~ — 완료(12종). 백엔드 9종(`#1201`) · `CLOUDFLARE_API_TOKEN`(`#1479`) · `API_ORIGIN`(`#1496`). 재발은 `test_deploy_secrets_are_listed_in_the_operations_secret_tables`가 막는다
- [ ] **커스텀 도메인** → 화면(Pages)은 아직 `bluelog-bx7.pages.dev`다. **API는 `bluelog-api.kpubdata.com`으로 확보**됐다(`#1496` · §3.5). 화면 도메인을 붙이면 `CORS_ALLOW_ORIGINS`·`APP_PUBLIC_URL`도 함께 바꾼다 (#785)
- [x] ~~**CUBRID 비밀번호 설정**~~ — 완료. `CUBRID_PASSWORD` 시크릿이 배포·헬스체크 양쪽에 쓰인다
- [ ] **DB 포트 게시 주소 실측**(`#1641`) → 적용 뒤 db-01에서 `ss -ltnp 'sport = :33100'`이 사설 IP 한 줄만 보이는지, 외부(공인 IP)에서 `nc -vz -w 5 132.226.170.195 33100`이 붙지 않는지 **사람이 한 번 확인**한다(§4.1). ⚠️ 2026-09-24 기준 미실측
- [ ] **ufw 활성화**(SSH만) → `ops/host/ufw-db-01.sh` 실행. ⚠️ ourtax와 공유하는 호스트라 **호스트 소유자 확인이 먼저**다. CUBRID 포트는 ufw 소관이 아니다(`#1641` · §4.1)
- [x] ~~**app-01 스왑**~~ — 완료(2026-09-25 · `#1911`). `/swapfile` 2GB · `/etc/fstab` 등록 · `swappiness=10`. 종전 항목은 「이미 our-tax에서 적용됐을 수 있음」이었고 **실제로는 스왑 0이었다** — 그 상태에서 배포가 호스트를 두 번 멈춰 세웠다. 다른 호스트에 적용할 때는 `sudo ops/host/setup-zram-swap.sh` 뒤 **`swapon --show`에 `/swapfile` 줄이 보이는지 확인한다**(zram만 있으면 재부팅에 사라진다)
- [ ] **백업 절차** → 정기 백업 스크립트 (#788)
- [ ] **모니터링** → 헬스 체크 주기적 확인 (#790)
