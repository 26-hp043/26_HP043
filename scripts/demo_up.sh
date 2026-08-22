#!/usr/bin/env bash
#
# 시연용 전체 기동 스크립트.
#
# DB → 마이그레이션 → 규제 파라미터 seed → 백엔드 → (안내) 순서로 올린다.
# 각 단계가 **실제로 준비됐는지 확인한 뒤** 다음으로 넘어간다 — `sleep`으로 넘기면
# 시연 중에 "떴는데 아직 안 된" 상태를 만난다.
#
# 사용:
#   bash scripts/demo_up.sh          DB + 백엔드까지
#   bash scripts/demo_up.sh --check  기동하지 않고 현재 상태만 점검
#
# 프론트엔드는 별도 창에서 띄운다 (아래 안내 참조).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Docker Desktop(WSL 통합 미설정 환경) 대비 — Windows 실행 파일을 직접 쓴다.
DOCKER="docker"
command -v docker >/dev/null 2>&1 || DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"

VENV="$ROOT/.venv/bin"
DB_URL="postgresql+asyncpg://cii:cii@localhost:5432/cii"
CHECK_ONLY="${1:-}"

# --- .venv 확인 -----------------------------------------------------------------------
#
# 이 스크립트는 alembic·seed·uvicorn을 전부 `$VENV`에서 부른다. 가상환경이 없으면
# `No such file or directory`만 나와서 **무엇을 해야 하는지 알 수 없다** (#477).
#
# 화면만 만지는 사람도 백엔드를 띄워야 하므로, 원인과 해결을 여기서 말해 준다.
#
# **`--check`는 막지 않는다 (#637).** 점검은 「기동하지 않고 상태만 본다」이고, 그중
# Docker·DB·백엔드 응답·계산 경로는 `.venv` 없이도 확인된다. Docker만 있는 환경에서
# 안내대로 우회 4단계를 손으로 돌린 뒤 **그것이 제대로 됐는지 확인해 주는 것은 이
# 스크립트뿐인데**, 종전에는 그 확인조차 막혀 있었다.
HAVE_VENV=0
[ -x "$VENV/python" ] && HAVE_VENV=1

if [ "$HAVE_VENV" = "0" ] && [ "$CHECK_ONLY" = "--check" ]; then
  printf '\033[33m!\033[0m Python 가상환경(.venv)이 없습니다 — 점검만 이어서 진행합니다.\n'
  printf '  마이그레이션 리비전 대조는 건너뜁니다(alembic이 .venv에 있습니다).\n\n'
fi

if [ "$HAVE_VENV" = "0" ] && [ "$CHECK_ONLY" != "--check" ]; then
  printf '\033[31m✗\033[0m Python 가상환경(.venv)이 없습니다.\n\n'
  printf '  이 스크립트는 alembic·seed·uvicorn을 .venv에서 실행합니다.\n'
  printf '  아래를 한 번 실행한 뒤 다시 시도하십시오.\n\n'
  printf '    python3 -m venv .venv\n'
  printf '    .venv/bin/pip install -e ".[dev]"\n\n'
  printf '  Python 없이 백엔드만 띄우려면 Docker 경로를 쓰십시오 (#477).\n\n'
  printf '    docker compose up -d --wait db\n'
  printf '    docker compose run --rm app alembic upgrade head\n'
  printf '    docker compose run --rm app python -m cii_platform.db.seed\n'
  printf '    docker compose run --rm app python -m cii_platform.db.demo_seed\n'
  printf '    docker compose up -d app\n\n'
  exit 1
fi

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
info() { printf '  · %s\n' "$1"; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# --- 1. Docker ---------------------------------------------------------------------

step "1. Docker"
if ! "$DOCKER" info >/dev/null 2>&1; then
  bad "Docker 데몬에 연결할 수 없습니다."
  info "Windows에서 Docker Desktop을 실행한 뒤 다시 시도하세요."
  info "이미 실행 중이라면 Settings → Resources → WSL Integration을 켜야 합니다."
  exit 1
fi
ok "Docker 응답함"

# --- 2. PostgreSQL -----------------------------------------------------------------

step "2. PostgreSQL"
if [ "$CHECK_ONLY" != "--check" ]; then
  "$DOCKER" compose up -d db >/dev/null 2>&1 || {
    bad "docker compose up 실패"; exit 1;
  }
fi

# healthcheck가 통과할 때까지 기다린다. 컨테이너가 '떴다'와 '접속 가능하다'는 다르다.
for i in $(seq 1 60); do
  if "$DOCKER" compose exec -T db pg_isready -U cii >/dev/null 2>&1; then
    ok "접속 가능 (${i}초)"
    break
  fi
  [ "$i" = 60 ] && { bad "60초 안에 준비되지 않았습니다."; exit 1; }
  sleep 1
done

# --- 3. 마이그레이션 ----------------------------------------------------------------

step "3. 마이그레이션"
export DATABASE_URL="$DB_URL"
if [ "$CHECK_ONLY" != "--check" ]; then
  "$VENV/alembic" upgrade head >/tmp/demo_alembic.log 2>&1 || {
    bad "alembic upgrade head 실패 — /tmp/demo_alembic.log 참조"; tail -5 /tmp/demo_alembic.log; exit 1;
  }
fi
# 리비전을 고정 값(과거엔 018)과 비교하지 않고 head와 비교한다 (#241).
# 마이그레이션이 추가되면 고정 비교가 항상 bad를 찍는다.
#
# `.venv`가 없으면 **확인 불가로 낸다 (#637).** `docker compose run`으로 대체할 수도
# 있으나, 그러면 `--check`가 컨테이너를 띄우게 되어 「기동하지 않고 상태만 본다」는
# 계약이 깨진다. **안 되는 것을 안 된다고 말하는 편이 낫다.**
if [ "$HAVE_VENV" = "1" ]; then
  HEAD_REV=$("$VENV/alembic" current 2>/dev/null | grep -oE '^[0-9]+' | head -1)
  EXPECTED_REV=$("$VENV/alembic" heads 2>/dev/null | grep -oE '^[0-9]+' | head -1)
  [ "$HEAD_REV" = "$EXPECTED_REV" ] && ok "리비전 $HEAD_REV (head)" || bad "리비전이 head($EXPECTED_REV)가 아닙니다: ${HEAD_REV:-없음}"
else
  info "리비전 대조를 건너뜁니다 — alembic이 .venv에 있습니다 (.venv 없음)"
fi

# --- 4. 규제 파라미터 seed -----------------------------------------------------------
#
# Z계수·기준선·d-vector는 마이그레이션이 아니라 스크립트가 넣는다(#127이 승격을 다룬다).
# 이게 없으면 계산 API가 409 PARAMETER_ERROR로 떨어진다.

step "4. 규제 파라미터 seed"
if [ "$CHECK_ONLY" != "--check" ]; then
  "$VENV/python" scripts/seed.py >/tmp/demo_seed.log 2>&1 || {
    bad "seed 실패 — /tmp/demo_seed.log 참조"; tail -5 /tmp/demo_seed.log; exit 1;
  }
fi

# --- 4b. 데모 데이터 -----------------------------------------------------------------
#
# 데모 선박·항차는 2026-08-17에 마이그레이션에서 분리됐다 (#451) — `alembic upgrade head`
# 만으로는 들어오지 않는다. 이것이 없으면 프론트엔드 고정표(referenceTable.ts)가 참조하는
# UUID가 DB에 없어 **첫 요청이 「그런 선박 없음」으로** 떨어진다.
#
# 멱등이라(ON CONFLICT DO NOTHING) 여러 번 실행해도 행이 늘지 않는다.

step "4b. 데모 데이터 (시연용 선박·항차)"
if [ "$CHECK_ONLY" != "--check" ]; then
  "$VENV/python" -m cii_platform.db.demo_seed >/tmp/demo_data.log 2>&1 || {
    bad "데모 데이터 적재 실패 — /tmp/demo_data.log 참조"; tail -5 /tmp/demo_data.log; exit 1;
  }
fi
# 행 수 집계 — `.venv`가 없으면 **이미 떠 있는 db 컨테이너에 직접 묻는다 (#637).**
#
# 종전에는 `$VENV/python`만 썼고, 없으면 「행 수 조회 실패」라는 **거짓 실패**를 냈다.
# `docker compose exec`는 **떠 있는 컨테이너에 붙는 것**이라 아무것도 기동하지 않는다
# — `--check`의 계약을 깨지 않는다(2단계가 이미 db가 떠 있음을 확인한 뒤다).
if [ "$HAVE_VENV" = "0" ]; then
  COUNTS=$("$DOCKER" compose exec -T db psql -U cii -d cii -tAc \
    "SELECT 'vessel=' || (SELECT count(*) FROM vessel)
         || ' · fuel_type=' || (SELECT count(*) FROM fuel_type)
         || ' · regulation_year=' || (SELECT count(*) FROM regulation_year)
         || ' · cii_reference_line=' || (SELECT count(*) FROM cii_reference_line)
         || ' · cii_rating_boundary=' || (SELECT count(*) FROM cii_rating_boundary)" 2>/dev/null | tr -d '\r')
else
COUNTS=$("$VENV/python" - <<'PY' 2>/dev/null
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        out = []
        for table in ("vessel", "fuel_type", "regulation_year", "cii_reference_line", "cii_rating_boundary"):
            out.append(f"{table}={await conn.scalar(text(f'SELECT count(*) FROM {table}'))}")
        print(" · ".join(out))
    await engine.dispose()

asyncio.run(main())
PY
)
fi
[ -n "$COUNTS" ] && ok "$COUNTS" || bad "행 수 조회 실패"

# --- 4c. 시드 보강분이 실제로 들어왔는가 (#587) ---------------------------------------
#
# **행 수만 세면 이 상태를 놓친다.** demo_seed는 `ON CONFLICT DO NOTHING`이라
# **기존 행을 갱신하지 않는다**(의도된 것이다 — 사용자가 고친 값을 덮지 않는다).
#
# 그래서 시드에 제원을 새로 채워도 **볼륨을 유지한 환경에는 영원히 들어가지 않는다.**
# 시연 노트북이 정확히 그 경우이며, 그 상태는 오류가 아니라 **화면의 `—`로만** 드러난다.
#
# `.venv`가 없으면 건너뛴다 — 대조에 시드 상수(파이썬)가 필요하다.
if [ "$HAVE_VENV" = "1" ]; then
  DRIFT=$(DATABASE_URL="$DB_URL" "$VENV/python" - <<'PY' 2>/dev/null
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from cii_platform.db.demo_seed import missing_seeded_specs

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        rows = await missing_seeded_specs(conn)
    await engine.dispose()
    print(" · ".join(f"{name}: {column}" for name, column in rows))

asyncio.run(main())
PY
)
  if [ -n "$DRIFT" ]; then
    printf '\033[33m!\033[0m 시드에는 있는데 DB에 없는 제원: %s\n' "$DRIFT"
    printf '  demo_seed는 기존 행을 덮지 않습니다. 데모 DB를 비우고 다시 넣으십시오.\n'
    printf '    %s compose down -v && bash scripts/demo_up.sh\n\n' "$DOCKER"
  else
    ok "시드 제원이 DB와 일치합니다"
  fi
fi

# --- 5. 백엔드 ----------------------------------------------------------------------

step "5. 백엔드 API"
if [ "$CHECK_ONLY" != "--check" ]; then
  pkill -f "uvicorn cii_platform" 2>/dev/null
  sleep 1
  nohup env DATABASE_URL="$DB_URL" "$VENV/uvicorn" cii_platform.api.main:app \
    --host 0.0.0.0 --port 8000 >/tmp/demo_api.log 2>&1 &
  disown
fi

for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then
    ok "http://localhost:8000 응답 (${i}초)"
    break
  fi
  [ "$i" = 30 ] && { bad "백엔드가 뜨지 않았습니다 — /tmp/demo_api.log 참조"; tail -10 /tmp/demo_api.log; exit 1; }
  sleep 1
done

# --- 6. 실제 계산 한 번 --------------------------------------------------------------
#
# **health만 확인하고 끝내지 않는다.** health는 DB를 건드리지 않으므로,
# 계산 경로가 실제로 도는지는 한 번 호출해 봐야 안다. 시연 중에 처음 알면 늦다.

step "6. 계산 경로 확인"

# 계산 경로는 **인증이 필요하다**. dev 세션을 발급받아 쿠키를 쥐고, 상태 변경
# 요청이므로 CSRF 토큰을 **헤더로** 붙인다 — 쿠키로도 오지만 검증은 헤더만 본다
# (`auth/dependencies.py`). `dev-login`은 `APP_ENV != production`에서만 등록된다
# (`API_SPEC §1.2`).
# 쿠키 jar는 **템플릿을 경로째 적어** 만든다.
#
# `mktemp -t demo_cii_jar`는 **GNU coreutils에서 거부된다** — `-t`의 템플릿은
# `XXX` 이상으로 끝나야 하고, 그렇지 않으면 `too few X's in template`으로
# 종료 코드 1을 낸다. BSD/macOS는 접미사를 알아서 붙여 통과하므로
# **리눅스·WSL에서만** 드러났다.
#
# 이 스크립트에는 `set -e`가 없다(위 `set -uo pipefail`). 그래서 실패해도
# 멈추지 않고 `JAR`이 빈 문자열이 된 채 진행했고, 뒤의 `awk`가 빈 결과를 내
# **「dev 세션을 발급받지 못했습니다」라는 원인이 아닌 메시지**가 떴다.
# 인증은 멀쩡했고 임시파일을 못 만든 것이었다 — `#616`이 없애려던
# 「원인을 알 수 없는 메시지」가 다른 형태로 되살아난 셈이다.
#
# 그래서 두 가지를 함께 한다.
#   1. 템플릿을 `"${TMPDIR:-/tmp}/…XXXXXX"`로 적는다 — GNU·BSD가 같게 동작한다
#   2. **실패를 그 자리에서 잡는다** — 빈 `JAR`로 다음 줄에 가지 않는다
JAR=$(mktemp "${TMPDIR:-/tmp}/demo_cii_jar.XXXXXX" 2>/dev/null) || JAR=""
if [ -z "$JAR" ]; then
  bad "임시 파일을 만들지 못했습니다 — 쿠키를 저장할 수 없어 인증을 진행할 수 없습니다"
  info "TMPDIR=${TMPDIR:-/tmp} 에 쓰기 권한이 있는지 확인하십시오."
  exit 1
fi
trap 'rm -f "$JAR"' EXIT

curl -s -c "$JAR" -X POST http://localhost:8000/api/v1/auth/dev-login >/dev/null 2>&1
CSRF=$(awk '$6=="csrf"{print $7}' "$JAR")

if [ -z "$CSRF" ]; then
  # **인증 실패와 계산 불일치를 구분한다.** 종전에는 둘 다 「기대값과 다릅니다」로
  # 나와 원인을 알 수 없었다 (#616).
  bad "dev 세션을 발급받지 못했습니다 — APP_ENV가 production이거나 백엔드가 인증을 거부합니다"
  printf '  확인: curl -i -X POST http://localhost:8000/api/v1/auth/dev-login\n'
  exit 1
fi

RESULT=$(curl -s -b "$JAR" -H "X-CSRF-Token: $CSRF" \
  -X POST http://localhost:8000/api/v1/calculations/voyage-cii \
  -H 'Content-Type: application/json' \
  -d '{"vessel_id":"00000000-0000-4000-8000-000000000001","regulation_year":2026,
       "distance_nm":1000,"speed_kn":14.2,"fuel_uses":[{"fuel_type":"HFO","fuel_ton":80}]}' 2>/dev/null)

# 응답에서 값을 꺼낸다 — **파이썬을 쓰지 않는다 (#637).**
#
# 이 세 값은 `curl` 응답에서 문자열을 집는 것뿐이라 실행 환경이 필요 없다. 종전에는
# `"$VENV/python"`으로 파싱해, **Docker만 있는 환경에서는 계산 경로 확인 자체가
# 불가능**했다. `jq`도 기대할 수 없으므로(설치돼 있지 않을 수 있다) `sed`로 집는다.
#
# 임의의 JSON을 다루는 것이 아니라 **우리가 만든 응답의 고정 필드**를 보는 것이라
# 성립한다. 형식이 바뀌면 값이 비고, 아래 분기가 원문 400자를 그대로 보여 준다 —
# 조용히 틀린 값을 만들지는 않는다.
_field() { printf '%s' "$2" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\).*/\1/p" | head -1; }

CII=$(_field attained_cii "$RESULT")
RATING=$(_field estimated_rating "$RESULT")

if [ "$CII" = "4.982400" ] && [ "$RATING" = "C" ]; then
  ok "attained_cii=$CII · rating=$RATING — 정본 픽스처와 일치"
else
  ERR_CODE=$(_field code "$RESULT")
  if [ -n "$ERR_CODE" ]; then
    bad "계산 요청이 거부됐습니다 (${ERR_CODE}) — 인증·CSRF 경로를 확인하십시오"
  else
    bad "기대값과 다릅니다: cii=${CII:-없음} rating=${RATING:-없음}"
  fi
  printf '%s\n' "$RESULT" | head -c 400; echo
  exit 1
fi

# --- 안내 ---------------------------------------------------------------------------

# 안내 문구는 README 「화면은 항상 실 API로 돈다」와 같은 것을 말해야 한다.
#
# 종전 안내는 **`#542`가 폐기한 데모 모드를 지시하고 있었다** — 「demo 모드
# (백엔드 안 씀)」 갈래와 `VITE_USE_API=true`가 그것이다. 그 환경변수를 읽는
# 코드는 저장소에 **한 줄도 없다**(남은 6곳은 전부 「종전에는」으로 시작하는
# 과거 서술 주석이다). 그대로 따르면 데모 모드인 줄 알고 실 API 화면을 보게
# 되며, 이는 `#528`이 만든 혼동의 반대 방향이다.
#
# Vite dev 서버가 `/api`를 `127.0.0.1:8000`으로 프록시하므로(#138) 갈래가
# 필요 없다. 로그인 우회 방법도 README와 같은 것을 적는다.
cat <<'GUIDE'

──────────────────────────────────────────────────────────────
 백엔드 준비 완료. 프론트엔드는 새 터미널에서 띄우세요.

   개발 서버 (코드 수정이 바로 반영됨)
     cd frontend && npm run dev            # http://localhost:5173

   프로덕션 빌드 확인
     cd frontend && npm run build && npx vite preview --port 4173

 화면은 항상 실 API로 돕니다 (#542) — 백엔드가 떠 있어야 데이터가 보입니다.
 로그인을 건너뛰려면 브라우저 콘솔에서:

     await fetch('/api/v1/auth/dev-login', { method: 'POST' }); location.href = '/'

 종료
     pkill -f "uvicorn cii_platform"
     docker compose down
──────────────────────────────────────────────────────────────
GUIDE
