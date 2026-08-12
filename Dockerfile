# CII 플랫폼 Python 앱 이미지
# TECH_SPEC §2.5.2 (환경 핀닝): Python 3.12 고정으로 재현성 확보
#
# 멀티스테이지 구성 (#85):
#   - dev  : 개발용 — --reload + editable install + 볼륨 마운트(호스트 소스)
#   - prod : 프로덕션용 — non-editable install, --reload 없음, 코드 이미지 고정
#
# docker-compose.yml(dev)은 build.target: dev, docker-compose.prod.yml은 build.target: prod를 지정한다.

# ---------- dev stage ----------
FROM python:3.12-slim AS dev

# PostgreSQL 드라이버(asyncpg) 빌드에 필요한 시스템 패키지
#  - libpq-dev: PostgreSQL client 라이브러리 헤더
#  - gcc: C 확장 컴파일러
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# build backend가 hatchling이고 pyproject의 packages=["src/cii_platform"]이므로
# editable install(pip install -e .)은 소스 디렉토리가 존재해야 성공한다.
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
CMD ["uvicorn", "cii_platform.api.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]

# ---------- prod stage ----------
FROM python:3.12-slim AS prod

# APP_ENV=production — config.py의 프로덕션 가드(#118)를 발동시킨다 (#231).
# 미설정 시 development로 떨어져 DATABASE_URL 누락에도 개발용 기본값으로 폴백한다 —
# #118이 막으려던 바로 그 상황. ENV는 이미지 빌드 시점에 굳으므로 compose 환경보다
# 우선한다. compose 쪽 APP_ENV는 가시성용 중복 명시(아래 docker-compose.prod.yml).
ENV APP_ENV=production

# dev와 동일한 빌드 의존성을 유지한다.
#  - asyncpg가 wheel 없이 소스 빌드되는 환경에서도 동일하게 빌드되도록 보장 (#85)
#  - gcc · libpq-dev는 빌드 시점에만, 런타임 이미지 최적화는 검증 후 별도 이슈로 분리
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

# 프로덕션은 non-editable install — 빌드 시점의 코드를 이미지에 고정한다 (#85)
RUN pip install --no-cache-dir .

EXPOSE 8000

# 프로덕션 서버 실행
#  - --reload 없음: 파일 폴링 오버헤드와 볼륨 마운트 결합 시 코드 주입 공격 표면 제거 (#85)
#  - 코드는 이미지 내부에 고정되어 있으므로 호스트 볼륨 마운트가 필요 없다.
CMD ["uvicorn", "cii_platform.api.main:app", "--host", "0.0.0.0", "--port", "8000"]