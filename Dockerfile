# CII 플랫폼 Python 앱 이미지
# TECH_SPEC §2.5.2 (환경 핀닝): Python 3.12 고정으로 재현성 확보
FROM python:3.12-slim

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
CMD ["uvicorn", "src.cii_platform.api.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
