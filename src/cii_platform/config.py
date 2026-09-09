"""애플리케이션 설정.

``DATABASE_URL``이 없을 때의 동작은 ``APP_ENV``에 따라 갈린다 (#118).
프로덕션에서는 개발용 기본값으로 조용히 폴백하지 않고 즉시 실패한다.
환경변수 누락이 "연결 거부"로 뒤늦게 드러나는 것을 막고, 개발용 credential이
운영 traceback에 남지 않게 하기 위함이다.
"""

import logging
import os

#: 모듈 로거. ``warnings.warn``은 기본 필터에서 모듈당 1회만 출력되고 uvicorn 로그로
#: 잘 올라오지 않아 폴백이 눈에 띄지 않는다 (#231). 로거를 쓰면 매 import마다 남는다.
_log = logging.getLogger(__name__)

#: ``APP_ENV``의 허용값 (#810).
#:
#: **모르는 값이면 기동을 거부한다.** 종전에는 원문을 그대로 ``== "production"``과
#: 비교했고, 검증이 어디에도 없었다 — ``prod``·``Production``·후행 공백 하나로
#: 프로덕션 가드 다섯이 **동시에, 조용히** 열렸다. 앱은 정상 기동하고 ``/health``도
#: 200이라 틀렸다는 신호가 남지 않는다.
#:
#: ``staging``·``test``는 현재 어느 배포 경로도 쓰지 않지만 허용값에 둔다. 허용
#: 목록이 배포 환경보다 좁으면, 환경을 늘리는 사람이 **가드를 여는 방향으로**
#: 우회하게 된다.
VALID_APP_ENVS = frozenset({"development", "test", "staging", "production"})

#: 프로덕션 환경 이름. ``"production"`` 리터럴을 이 한 곳으로 모은다 — 리터럴이
#: ``config.py``·``routes/auth_dev.py``·``mail/config.py`` 셋에 흩어져 있던 것이
#: `#810`의 원인이다. 비교는 :func:`is_production_env`로만 한다.
_PRODUCTION = "production"

#: ``APP_ENV`` 미설정·빈 값일 때의 환경.
#:
#: ``.env.example``은 이 변수를 **설정하지 않는다** (#810) — 그 파일을 그대로
#: ``.env``로 복사하면 ``docker-compose.prod.yml``의 ``${APP_ENV:-production}`` 치환이
#: 그 값을 읽어 **프로덕션 스택이 development로 뜬다.** 개발에는 값이 필요 없다:
#: 미설정이 여기서 ``development``가 되고, ``docker-compose.yml``은 이 변수를
#: 컨테이너에 넘기지도 않는다.
_DEFAULT_APP_ENV = "development"


def normalize_app_env(raw: str | None) -> str:
    """``APP_ENV`` 원문을 정규화하고 허용값인지 확인한다 (#810).

    ## 왜 정규화만으로는 부족한가

    ``.strip().lower()``만 하면 ``Production``·``"production "``은 구제되지만
    ``prod``·``prd``·``PROD``는 여전히 ``development``로 떨어진다 — 그리고 그 결과가
    **가드 다섯이 열린 채 정상 기동**이다. 그래서 정규화 **다음에** 허용값 검증을
    두고, 모르는 값이면 ``RuntimeError``로 기동을 세운다.

    ## 왜 반대로 「엄격 일치만」 하지 않는가

    ``Production``을 거부하는 안도 fail-open을 없애지만, 대문자 하나로 운영 배포가
    서는 대가를 치른다. **두 안 모두 「production 의도인데 dev로 열린다」를 제거하며
    차이는 관용도뿐**이므로, ``MAIL_BACKEND``가 이미 쓰는 저장소 관례
    (``.strip().lower()`` 후 허용값 검증, ``mail/config.py:54``)를 따른다.
    정규화가 값을 바꾸면 **경고 로그를 남겨** 「틀렸다는 신호」는 보존한다.

    :raises RuntimeError: 정규화 후에도 :data:`VALID_APP_ENVS`에 없는 값일 때.
    """
    if raw is None:
        return _DEFAULT_APP_ENV

    value = raw.strip().lower()
    if not value:
        return _DEFAULT_APP_ENV

    if value not in VALID_APP_ENVS:
        raise RuntimeError(
            f"APP_ENV 값이 올바르지 않습니다: {raw!r}. "
            f"허용: {', '.join(sorted(VALID_APP_ENVS))}. "
            "모르는 값을 development로 취급하면 dev-login·/docs·데모 계정 시드·"
            "DB URL 폴백·console 메일 백엔드가 프로덕션에서 함께 열립니다."
        )

    if value != raw:
        _log.warning("APP_ENV %r을 %r로 정규화했습니다.", raw, value)

    return value


def is_production_env(app_env: str) -> bool:
    """정규화된 ``APP_ENV`` 값이 프로덕션인가 (#810).

    :func:`is_production`은 이 모듈이 읽은 값에 대해 이것을 부른다.
    ``mail/config.py``는 테스트 주입용 dict에서 읽은 값에 대해 부른다 — 그쪽이
    ``os.environ``을 다시 읽고 ``== "production"`` 리터럴 비교를 하던 것이
    **`#810`이 놓칠 뻔한 다섯 번째 가드**였다.
    """
    return app_env == _PRODUCTION


# 환경 구분. 미설정 시 개발 환경으로 본다. 모르는 값이면 여기서 기동이 선다 (#810).
_ENV = normalize_app_env(os.environ.get("APP_ENV"))

# 로컬 개발용 기본 접속 URL. docker-compose.yml · .env.example과 같은 값이다.
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://cii:cii@localhost:5432/cii"

_url = os.environ.get("DATABASE_URL")

if _url is None:
    if is_production_env(_ENV):
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다 (APP_ENV=production). "
            "프로덕션에서는 개발용 기본값으로 폴백하지 않습니다."
        )
    _log.warning(
        "DATABASE_URL이 없어 개발용 기본값을 사용합니다: %s",
        _DEFAULT_DATABASE_URL,
    )
    _url = _DEFAULT_DATABASE_URL

DATABASE_URL: str = _url


def is_production() -> bool:
    """``APP_ENV=production``인가 — 환경 분기의 단일 출처 (#648).

    아래 두 판정(:func:`should_expose_dev_auth`·:func:`should_expose_api_docs`)이 같은
    말을 두 번 쓰지 않게 한다. ``routes/auth_dev.py``의 ``should_register_dev_auth()``도
    `#810`에서 :func:`should_expose_dev_auth` 위임으로 바꿔 **판정이 하나만 남았다** —
    그전에는 그쪽이 ``config._ENV``라는 private 이름을 import해 ``!= "production"``으로
    다시 비교했다.

    읽는 값은 :func:`normalize_app_env`를 통과한 것이므로 ``Production``·
    ``"production "``도 여기서 True다 (#810).
    """
    return is_production_env(_ENV)


def should_expose_dev_auth() -> bool:
    """dev-login을 여는가 — ``routes/auth_dev.py``도 이 함수를 부른다 (#648 · #810).

    ## 왜 판정이 여기에 있는가

    ``auth/dependencies.py``의 공개 경로 목록이 이 값을 필요로 하는데, 거기서
    ``routes/auth_dev.py``를 import하면 **``TECH_SPEC §16`` 계층 규칙을 어긴다** —
    auth는 routes보다 아래층이다. 그래서 두 소비자(``auth/dependencies.py``와
    ``routes/auth_dev.py``)보다 아래인 ``config.py``에 둔다.

    ## 종전에는 판정이 둘이었다 (#810에서 하나로)

    ``routes/auth_dev.py``의 ``should_register_dev_auth()``가 ``config._ENV``라는
    **private 이름을 import**해 ``_ENV != "production"``으로 **다시** 비교했다.
    부정형이라 ``APP_ENV``에 모르는 값이 들어오면 **여는 쪽으로** 틀렸고, 아래에 적힌
    「갈리면 무슨 일이 생기는가」가 실제로 일어날 수 있는 배선이었다. 지금은
    ``should_register_dev_auth()``가 이 함수를 그대로 위임한다.

    ## 갈리면 무슨 일이 생기는가

    ``#276``이 프로덕션에서 dev-login **라우트를 등록하지 않는데** 공개 경로 목록에는
    그대로 남아 있었다. ``is_public_path()``가 완전일치 허용 목록이라 목록에 있으면
    미들웨어를 통과하고 → 라우트가 없어 **404**가 된다. 다른 미등록 경로는 전부
    **401**이므로 **그 경로만 응답이 달라진다** — `#593`이 ``/docs``에서 없앤 것과
    같은 신호다.

    **두 판정이 어긋나면 ``tests/test_docs_exposure.py``가 잡는다.**
    """
    return not is_production()


def should_expose_api_docs() -> bool:
    """``APP_ENV=production``이면 False — OpenAPI 문서를 열지 않는다 (#593).

    ## 무엇을 막는가

    ``/docs``·``/redoc``·``/openapi.json``은 FastAPI 기본값이 **항상 켜짐**이라,
    프로덕션에서도 **세션 없이 API 전체 구조**를 읽을 수 있었다 — 엔드포인트 50종,
    요청 스키마, 필드명, 검증 규칙. 인증이 필요한 엔드포인트는 그대로 보호되므로
    그 자체가 취약점은 아니지만, 노출할 이유도 없다. **스펙의 정본은 저장소의
    ``API_SPEC.md``**라 운영 중 조회가 필요하지 않다.

    ## 왜 이 함수가 ``config.py``에 있는가

    ``api/main.py``(문서 라우트 등록)와 ``auth/dependencies.py``(공개 경로 목록)가
    **둘 다** 이 판정을 쓴다. 어느 한쪽에 두면 다른 쪽이 import 순환을 만든다.
    ``APP_ENV``를 읽는 곳이 여기이므로 판정도 여기에 둔다.

    ``routes/auth_dev.py``의 ``should_register_dev_auth()``와 **같은 형태**다 —
    런타임 조건 분기가 아니라 **기동 시점에** 가른다. 요청마다 판정하면 환경변수를
    바꿔 켤 수 있는 것처럼 읽히고, 실제로는 프로세스 수명 동안 바뀌지 않는다.
    """
    return not is_production()


#: 프로덕션에서 ``APP_PUBLIC_URL``이 없을 때의 문구 (#809). 기동 검증과 호출 시점
#: 방어가 **같은 문장**을 쓰도록 상수로 둔다 — 두 곳이 갈리면 운영자가 같은 원인을
#: 다른 문제로 읽는다.
_PUBLIC_URL_REQUIRED = (
    "APP_PUBLIC_URL 환경변수가 설정되지 않았습니다 (APP_ENV=production). "
    "미설정 시 메일 링크가 요청의 Host 헤더를 따라가, 공격자가 그 헤더를 바꾸면 "
    "정상 발신지에서 온 메일에 공격자 도메인 링크가 실립니다."
)


def public_base_url(fallback: str) -> str:
    """메일 링크의 기준 주소 (#429).

    ``/verify-email``·``/password-reset``은 **프론트엔드 라우트**다. API 서버에는
    그 경로가 없으므로, 메일 링크는 사용자가 실제로 화면을 여는 주소를 가리켜야 한다.

    ## 왜 폴백을 남기는가

    종전 구현은 ``request.base_url``만 썼고, 그 근거를 *"설정으로 따로 두면 그 값이
    실제 서비스 주소와 어긋났을 때 링크가 조용히 죽는다"* 라고 적었다. **그 우려는
    지금도 유효하다** — 다만 그것이 「설정을 두지 않을 이유」는 아니었다.

    운영은 nginx 뒤에서 프론트와 API가 **같은 origin**이라 요청 주소가 정확하다.
    개발은 Vite(5173)와 FastAPI(8000)가 **다른 origin**이라 요청 주소가 언제나 틀린다.
    그래서 **설정이 있으면 설정을, 없으면 요청 주소를** 쓴다 — 같은 origin 배포는
    설정 없이 지금 동작을 그대로 유지하고, 분리된 환경만 명시한다.

    :param fallback: 미설정 시 쓸 주소. 호출부가 ``str(request.base_url)``을 넘긴다.
        **설정을 읽지 못한 것과 요청 주소를 쓰기로 한 것을 구분**하기 위해 인자로
        받는다 — 이 함수가 ``Request``를 알면 레이어 방향이 뒤집힌다.
    """
    configured = os.environ.get("APP_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    if is_production():
        raise RuntimeError(_PUBLIC_URL_REQUIRED)
    return fallback.rstrip("/")


def validate_public_base_url() -> None:
    """기동 시점에 ``APP_PUBLIC_URL`` 설정을 확인한다 (#809).

    ## 왜 기동 시점인가

    ``#524``가 메일 백엔드에 대해 같은 판단을 했다. 가드가 **첫 발송 시도**에서야
    돌면, 드러나는 시점이 「배포 직후」가 아니라 **「첫 사용자가 계정을 잃을 뻔한
    순간」**이 된다.

    여기서는 그보다 나쁘다 — 메일 백엔드는 실패하면 500이라도 나지만, 이쪽은
    **아무 오류 없이 공격자 도메인 링크가 발송**된다. 조용히 성공하는 결함이다.

    ## 무엇을 하지 않는가

    **주소가 실제로 살아 있는지 확인하지 않는다.** 기동을 외부 가용성에 묶는 일이고,
    형식이 맞는데 응답이 없는 것은 배포가 멈춰야 할 이유가 아니다. 여기서 보는 것은
    **설정이 있는가**뿐이다.
    """
    if not is_production():
        return
    if not os.environ.get("APP_PUBLIC_URL", "").strip():
        raise RuntimeError(_PUBLIC_URL_REQUIRED)
