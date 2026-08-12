# CI(이슈 #25)의 test job이 실제로 동작함을 증명하기 위한 최소 스모크 테스트.
# 현재 프로젝트에는 실제 테스트가 0개라 pytest가 exit code 5(no tests collected)를
# 반환해 test job이 실패한다. 아래 테스트는 config 모듈이 정상 로드되고 핵심
# 설정값(DATABASE_URL)이 유효하게 채워지는지를 검증한다. 향후 기능 개발 시
# 각 기능에 맞는 테스트를 이 골격 위에 추가한다.
#
# #118에서 APP_ENV 기반 프로덕션 가드 테스트를 추가했다.

import importlib

import pytest

from cii_platform import __version__, config

# config가 읽는 환경변수. 재로드 전에 전부 비워 테스트 간 잔류를 막는다.
_CONFIG_ENV_KEYS = ("APP_ENV", "DATABASE_URL")

# 개발용 기본 접속 URL. config._DEFAULT_DATABASE_URL을 참조하면 검증이
# 자기참조가 되므로, docker-compose.yml · .env.example과 같은 리터럴로 대조한다.
_DEV_DEFAULT_URL = "postgresql+asyncpg://cii:cii@localhost:5432/cii"


@pytest.fixture
def reload_config(monkeypatch):
    """환경변수를 지정해 config 모듈을 재로드하고, 종료 시 원래 상태로 복원한다.

    격리가 필요한 이유: importlib.reload는 기존 모듈 네임스페이스에서 코드를
    다시 실행한다. 프로덕션 경로 테스트는 실행 도중 RuntimeError로 중단되므로
    _ENV·_url 같은 모듈 상태가 테스트가 지정한 값 그대로 sys.modules에 남는다.
    conftest.py·alembic/env.py·scripts/seed.py가 모두 이 모듈을 참조하기 때문에
    복원하지 않으면 이후 테스트가 영향을 받는다.
    """

    def _reload(**env: str):
        for key in _CONFIG_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload

    # 환경변수를 먼저 원복한 뒤 재로드해야 모듈이 원래 환경 기준으로 돌아온다.
    # monkeypatch 자체의 teardown은 이 함수보다 나중에 돌기 때문에 직접 호출한다.
    monkeypatch.undo()
    importlib.reload(config)


def test_config_module_loads_database_url():
    """config 모듈이 로드되고 DATABASE_URL이 유효한 PostgreSQL 접속 문자열로 채워진다."""
    # 설정이 제대로 로드되면 문자열 타입의 비어있지 않은 값이어야 한다.
    assert isinstance(config.DATABASE_URL, str)
    assert config.DATABASE_URL, "DATABASE_URL이 비어 있으면 안 된다"

    # 기본값이든 환경변수 override든 PostgreSQL 접속 URL이어야 한다.
    # (CI에서는 env DATABASE_URL=postgresql://cii:cii@localhost:5432/cii_test 로 주입됨)
    assert config.DATABASE_URL.startswith("postgresql")


def test_package_version_is_defined():
    """패키지 메타데이터(__version__)가 정상적으로 노출된다."""
    assert __version__
    assert isinstance(__version__, str)


def test_production_without_database_url_raises(reload_config):
    """프로덕션에서 DATABASE_URL이 없으면 개발용 기본값으로 폴백하지 않고 즉시 실패한다."""
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        reload_config(APP_ENV="production")


def test_development_without_database_url_warns_and_uses_default(reload_config, caplog):
    """개발 환경에서 DATABASE_URL이 없으면 경고 후 개발용 기본값을 쓴다.

    ``logging.warning``을 쓴다 (#231) — ``warnings.warn``은 기본 필터에서 모듈당
    1회만 출력되고 uvicorn 로그로 잘 안 올라와 폴백이 눈에 띄지 않았다.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="cii_platform.config"):
        reloaded = reload_config(APP_ENV="development")

    assert "개발용 기본값" in caplog.text
    assert reloaded.DATABASE_URL == _DEV_DEFAULT_URL


def test_unset_app_env_falls_back_to_development(reload_config, caplog):
    """APP_ENV 미설정은 development와 동일하게 동작한다.

    os.environ.get("APP_ENV", "development")의 기본 인자를 검증한다. 기본값이
    잘못된 문자열로 바뀌면 APP_ENV를 명시하는 위 테스트는 통과하고 이 테스트만
    실패한다.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="cii_platform.config"):
        reloaded = reload_config()

    assert "개발용 기본값" in caplog.text
    assert reloaded.DATABASE_URL == _DEV_DEFAULT_URL


def test_production_with_database_url_uses_provided_value(reload_config):
    """프로덕션이라도 DATABASE_URL이 있으면 가드가 발동하지 않고 그 값을 쓴다."""
    url = "postgresql+asyncpg://appuser:secret@db.internal:5432/cii"
    reloaded = reload_config(APP_ENV="production", DATABASE_URL=url)

    assert url == reloaded.DATABASE_URL
