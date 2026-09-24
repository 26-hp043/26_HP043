# CII 플랫폼 Python 앱 이미지
# TECH_SPEC §2.5.2 (환경 핀닝): Python 3.12 고정으로 재현성 확보
#
# 멀티스테이지 구성 (#85, #232):
#   - dev     : 개발용 — --reload + editable install + 볼륨 마운트(호스트 소스)
#   - builder : wheel만 만드는 중간 단계 — gcc·libpq-dev는 여기서만 (#232)
#   - prod    : 런타임 전용 — slim + libpq5 + 비루트 + HEALTHCHECK (#232)
#
# docker-compose.yml(dev)은 build.target: dev, docker-compose.prod.yml은 build.target: prod를 지정한다.

# ---------- dev stage ----------
FROM python:3.12-slim AS dev

# CUBRID Python 드라이버(pycubrid/aiopycubrid)는 순수 Python이라 C 빌드 도구가
# 불필요하지만, 다른 의존성(cffi 등)이 gcc를 쓸 수 있어 남겨 둔다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# 리포트 PDF 렌더링 (#361) — WeasyPrint 런타임.
#  - libpango-1.0-0 · libpangoft2-1.0-0: WeasyPrint가 텍스트 셰이핑에 쓴다.
#    한글은 자모 조합이라 셰이퍼 없이는 글자가 어긋난다.
#  - fonts-nanum: 한국어 폰트 (SIL Open Font License 1.1 — 임베딩·재배포 허용).
#    없으면 PDF의 한글이 오류가 아니라 **tofu(□□□)로 조용히** 렌더링된다.
#    fonts-noto-cjk는 한·중·일을 모두 담아 이미지가 ~300MB 늘어난다 — 이 제품의
#    문서는 한국어이므로 한국어 폰트만 넣는다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# build backend가 hatchling이고 pyproject의 packages=["src/cii_platform"]이므로
# editable 설치(pip install -e .)은 소스 디렉토리가 존재해야 성공한다.
# 따라서 pyproject.toml과 src를 install 이전에 함께 복사한다.
# (src 없이 pip install -e . 를 실행하면 빌드가 실패한다.)
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# 개발 서버 실행 (자동 리로드)
#  - --host 0.0.0.0: 컨테이너 외부(호스트)에서 접근 가능하도록 바인딩
#  - --port 8000: docker-compose 포트 매핑(8000:8000)과 일치
#  - 패키지 설치 후 모듈 경로는 cii_platform.api.main:app (src. 접두 불필요, #85)
#
# uvicorn 앞에 depcheck를 둔다 (#523). 이미지가 구워진 뒤 pyproject에 런타임
# 의존성이 추가되면 **앱이 기동조차 못 하는데** 그 오류가 원인을 가리키지 않는다
# (`RuntimeError: Form data requires "python-multipart"` → pip install 하라고
# 안내하지만 컨테이너 안에서는 틀린 해법이다). 대조는 100ms 안쪽이며, 실패하면
# 재빌드 명령을 찍고 멈춘다.
#
# exec 형식이 아니라 sh -c인 이유 — 두 명령을 잇기 위해서다. dev 전용이므로
# 시그널 전달의 미세한 차이는 감수한다. prod stage는 exec 형식 그대로다.
CMD ["sh", "-c", "python -m cii_platform.depcheck && exec uvicorn cii_platform.api.main:app --reload --host 0.0.0.0 --port 8000"]

# ---------- builder stage ----------
# wheel만 만들고 runtime으로 복사한다 — gcc·libpq-dev가 최종 이미지에 남지 않게 (#232).
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

# 프로젝트 wheel + 의존성 wheel을 /wheels에 만든다.
# runtime stage에서 pip install /wheels/*.whl 한 번에 프로젝트와 의존성이 같이 깔린다.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip wheel --no-cache-dir --wheel-dir=/wheels .

# ---------- prod stage ----------
# 런타임 전용 — gcc · libpq-dev · 헤더가 없다 (#232).
FROM python:3.12-slim AS prod

# APP_ENV=production — config.py 프로덕션 가드(#118) 발동 (#231).
# 미설정 시 development로 떨어져 DATABASE_URL 누락에도 개발용 기본값으로 폴백한다.
# ENV는 빌드 시점에 굳어 compose 환경보다 우선한다.
ENV APP_ENV=production

# CUBRID Python 드라이버는 순수 Python이라 libpq가 불필요하다.
# libpango·fonts-nanum은 리포트 PDF 렌더링용이다 (#361).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# 비루트 사용자 — uvicorn이 root로 돌지 않게 (#232).
# 애플리케이션 취약점 하나가 이미지 전체 쓰기 권한을 갖는 것을 막는다.
RUN useradd --create-home --uid 1000 cii
WORKDIR /app
RUN chown cii:cii /app

# builder에서 만든 wheel을 설치한다. --no-index --find-links로 PyPI 접근 없이
# /wheels에서만 해결한다 — runtime 이미지가 빌드 시점 이후 PyPI 상태에 영향받지 않게.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels cii_platform \
    && rm -rf /wheels

# 마이그레이션 정의를 이미지에 넣는다 (#240).
#  - alembic CLI 자체는 이미 있다 — pyproject의 **런타임** 의존성이라 wheel과 함께 깔린다.
#    없는 것은 설정(alembic.ini)과 버전 스크립트(alembic/)뿐이었다.
#  - 이것이 없으면 `docker compose exec app alembic upgrade head`가 설정을 찾지 못해
#    실패하고, 스키마 없이 뜬 API가 500을 낸다. #240 완료 기준이 이 명령을 전제한다.
#  - #232가 prod 이미지에서 뺀 것은 **빌드 도구**(gcc·libpq-dev)이지 마이그레이션
#    정의가 아니다. alembic/은 416K·31파일로 이미지 크기 영향이 미미하다.
#  - env.py는 cii_platform.{config,db.models,db.url}만 import하므로 그대로 동작한다.
#    env.py의 sys.path.insert는 존재하지 않는 src/ 경로를 넣으려 할 뿐이라 무해하다.
COPY alembic.ini ./
COPY alembic ./alembic

# 구조화 로그(#827 ⑵) — prod compose가 /app/logs 볼륨을 마운트한다. 익명 볼륨은
# 첫 마운트에서 **이미지 디렉터리의 소유자를 그대로 복제**하므로, cii가 쓸 수 있게
# 이미지에서 만들어 둔다. 없으면 USER cii로 뜬 앱이 PermissionError로 죽는다(실측).
RUN mkdir -p /app/logs && chown cii:cii /app/logs

USER cii

# 배포 커밋 식별자 (#789) — `GET /api/v1/health`가 `commit`으로 싣는다. 배포 빌드가
# `--build-arg GIT_SHA=<12자리>`로 넘긴다. 로컬 빌드처럼 넘기지 않으면 비고, 그때 응답은
# null(알 수 없음)이다. **마지막 층에 둔다** — 커밋마다 값이 바뀌므로 앞에 두면 apt·pip 층
# 캐시가 매번 깨진다.
ARG GIT_SHA=""
ENV BLUELOG_COMMIT=${GIT_SHA}

EXPOSE 8000

# HEALTHCHECK — /api/v1/health (API_SPEC §10).
# 컨테이너가 살아 있지만 응답하지 않는 상태를 오케스트레이터가 감지하게 한다 (#232).
# curl이 런타임 이미지에 없으므로 python urllib로 검사한다.
# interval·retries는 docker-compose.yml의 db healthcheck와 톤을 맞춘다.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=2).status==200 else 1)"

# 프로덕션 서버 실행
#  - --workers를 붙이지 않는다(기본 1). Layer 1 Decimal 컨텍스트가 스레드 로컬이라
#    워커마다 독립적으로 초기화돼야 한다 (TECH_SPEC §5.4 7항 · precision.py 모듈
#    docstring). --workers > 1로 확장 시 각 워커의 import 시점에 calc 패키지가
#    apply_default_rounding()을 호출하는지 확인해야 한다.
#  - 요청 한도 카운터도 워커별 프로세스 메모리다. --workers > 1이면 실효 한도가
#    워커 수만큼 곱해지므로, 확장 전 공유 저장소로 전환해야 한다 (#853).
#  - --reload 없음: 파일 폴링 오버헤드와 볼륨 마운트 결합 시 코드 주입 공격 표면 제거 (#85)
CMD ["uvicorn", "cii_platform.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
