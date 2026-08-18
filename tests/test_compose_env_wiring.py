"""이슈 #508 · compose가 `.env`를 컨테이너에 주입하는지 고정한다.

**막으려는 것은 설정이 없는 것이 아니라, 없다는 사실이 보이지 않는 상태다.**

compose가 프로젝트 루트의 ``.env``를 읽는 것은 compose 파일 안의 ``${POSTGRES_USER}``
같은 **치환용**이지 컨테이너 주입이 아니다. 그 차이를 몰라서 ``app`` 서비스가
``DATABASE_URL`` 하나만 받았고, ``MAIL_BACKEND``가 비어 ``mail/config.py``의 기본값
``console``이 적용됐다 — **메일이 실제로 나가지 않고 로그로만 출력됐다.**

그 실패가 조용한 이유는 두 겹이다.

1. 개발에서는 ``console``이 정상 동작이라 경고가 신호가 되지 않는다
2. 컨테이너에 ``APP_ENV``조차 안 들어가 기본값 ``development``가 되므로,
   ``load_mail_settings()``의 운영 가드(``production`` + ``console`` → ``RuntimeError``)도
   걸리지 않는다

`#429`가 고친 메일 링크 주소(``APP_PUBLIC_URL``)도 같은 이유로 이 경로에서 무효였다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DEV = _ROOT / "docker-compose.yml"
_PROD = _ROOT / "docker-compose.prod.yml"
_ENV_EXAMPLE = _ROOT / ".env.example"

#: 앱이 실제로 읽는 환경변수. ``os.environ``·``source.get(...)`` 양쪽을 모두 훑는다.
_ENV_READ = re.compile(r'(?:environ|source|env)\.get\(\s*"([A-Z][A-Z0-9_]*)"')
_ENV_INDEX = re.compile(r'environ\[\s*"([A-Z][A-Z0-9_]*)"\s*\]')


def _compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _app_service(path: Path) -> dict:
    return _compose(path)["services"]["app"]


def _env_file_entries(service: dict) -> list[dict]:
    """``env_file`` 항목을 dict 형태로 정규화한다.

    compose는 짧은 형태(``env_file: .env``)와 긴 형태(``- path: .env``)를 모두 받는다.
    """
    raw = service.get("env_file", [])
    if isinstance(raw, str):
        raw = [raw]
    return [{"path": e} if isinstance(e, str) else e for e in raw]


def test_dev_app_loads_env_file():
    """개발 compose의 ``app``이 ``.env``를 컨테이너에 주입한다."""
    entries = _env_file_entries(_app_service(_DEV))
    paths = [e.get("path") for e in entries]
    assert ".env" in paths, (
        "docker-compose.yml의 app 서비스에 env_file이 없다. "
        "compose가 .env를 읽는 것은 치환용이지 컨테이너 주입이 아니다 (#508)."
    )


def test_prod_app_loads_env_file():
    """운영 compose도 같다 — 여기서 비면 재설정 메일이 로그로만 나간다."""
    paths = [e.get("path") for e in _env_file_entries(_app_service(_PROD))]
    assert ".env" in paths, "docker-compose.prod.yml의 app 서비스에 env_file이 없다 (#508)."


def test_env_file_is_optional():
    """``.env``가 없어도 스택이 뜬다.

    ``.env``는 gitignore 대상이라 **CI와 새 클론에는 없다.** 필수로 두면 CI의 docker
    잡(`.github/workflows/ci.yml`)이 파일 부재로 깨진다 — 그 잡은 셸 환경변수만으로
    이 스택을 띄운다.
    """
    for path in (_DEV, _PROD):
        for entry in _env_file_entries(_app_service(path)):
            assert entry.get("required") is False, (
                f"{path.name}의 env_file이 필수로 잡혀 있다. "
                ".env는 커밋되지 않으므로 required: false여야 한다."
            )


def test_database_url_overrides_env_file():
    """``environment:``가 ``.env``의 ``DATABASE_URL``을 덮는다.

    ``.env``의 값은 호스트에서 ``uvicorn --env-file .env``로 띄울 때 쓰는
    ``localhost:5432``다. 컨테이너 안에서 그 주소는 **컨테이너 자신**을 가리키므로
    반드시 서비스 이름(``db``)으로 덮어써야 한다.

    compose는 ``environment:``를 ``env_file:``보다 우선하므로, 키가 거기 있기만 하면
    성립한다. 그 사실을 여기서 고정한다 — 지우면 조용히 잘못된 DB를 본다.
    """
    for path in (_DEV, _PROD):
        env = _app_service(path).get("environment", {})
        assert "DATABASE_URL" in env, f"{path.name}의 environment에 DATABASE_URL이 없다."
        assert "@db:5432/" in env["DATABASE_URL"], (
            f"{path.name}의 DATABASE_URL이 컨테이너 네트워크 주소를 가리키지 않는다: "
            f"{env['DATABASE_URL']}"
        )


def test_env_example_documents_every_variable_the_app_reads():
    """앱이 읽는 환경변수가 ``.env.example``에 전부 적혀 있다.

    본보기에 없는 변수는 **존재를 아는 방법이 없다.** ``.env``는 커밋되지 않으므로
    새로 합류한 사람이 참고할 수 있는 목록은 이 파일뿐이다.

    주석 처리된 줄(``# SMTP_HOST=...``)도 적힌 것으로 본다 — 선택 입력임을 그 형태로
    표현하고 있다.
    """
    src = _ROOT / "src"
    read: set[str] = set()
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        read |= set(_ENV_READ.findall(text))
        read |= set(_ENV_INDEX.findall(text))

    example = _ENV_EXAMPLE.read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.M))

    missing = sorted(read - documented)
    assert not missing, (
        f".env.example에 없는 환경변수를 앱이 읽는다: {', '.join(missing)}. "
        "본보기에 없으면 그 변수의 존재를 아는 방법이 없다."
    )
