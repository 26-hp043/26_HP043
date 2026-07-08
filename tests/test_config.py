# CI(이슈 #25)의 test job이 실제로 동작함을 증명하기 위한 최소 스모크 테스트.
# 현재 프로젝트에는 실제 테스트가 0개라 pytest가 exit code 5(no tests collected)를
# 반환해 test job이 실패한다. 아래 테스트는 config 모듈이 정상 로드되고 핵심
# 설정값(DATABASE_URL)이 유효하게 채워지는지를 검증한다. 향후 기능 개발 시
# 각 기능에 맞는 테스트를 이 골격 위에 추가한다.

from cii_platform import __version__, config


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
