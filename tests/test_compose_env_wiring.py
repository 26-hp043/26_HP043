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

#: OCI 분리 토폴로지의 app 호스트 스택과 그 본보기 (#1290).
#:
#: **`docs/OPERATIONS.md §4.3`이 지시하는 실제 배포 경로가 이 둘이다** (`cp
#: .env.app.example .env` → `docker compose -f docker-compose.prod.app.yml up -d`).
#: 그런데 이 파일을 보는 검사가 이 모듈에 하나도 없었다 — 위 `_DEV`·`_PROD`만 봤다.
_PROD_APP = _ROOT / "docker-compose.prod.app.yml"
_APP_ENV_EXAMPLE = _ROOT / ".env.app.example"

#: 앱이 실제로 읽는 환경변수. ``os.environ``·``source.get(...)`` 양쪽을 모두 훑는다.
_ENV_READ = re.compile(r'(?:environ|source|env)\.get\(\s*"([A-Z][A-Z0-9_]*)"')
_ENV_INDEX = re.compile(r'environ\[\s*"([A-Z][A-Z0-9_]*)"\s*\]')

#: **이름을 상수에 담아 읽는 경우** (#1290).
#:
#: 위 둘은 괄호 안이 리터럴일 때만 잡는다. ``auth/role_bootstrap.py``는
#: ``ENV_NAME = "INITIAL_ADMIN_EMAILS"``를 두고 ``env.get(ENV_NAME)``으로 읽는데 —
#: 오류 문구가 같은 이름을 쓰므로 상수로 두는 편이 옳다 — 그래서 **이 가드에 잡히지
#: 않았고, 그 변수는 두 본보기 어디에도 없는 채로 통과했다.** 배포가 그 값을 비운 채
#: 뜨면 새 DB는 사무직 0명이 되고, 승격 경로도 사무직 전용이라 화면으로는 아무도
#: 풀 수 없다 (`#672` · `API_SPEC §1.2`).
#:
#: 가드가 「있는 척」만 하는 쪽이 없는 것보다 나쁘다 — 그래서 **정규식을 넓히는 쪽**을
#: 골랐다. 반대 안(상수를 없애고 리터럴로 읽게 한다)은 같은 문자열을 두 곳에 두게 되고,
#: 그것이야말로 이 가드가 막으려는 종류의 어긋남이다.
_ENV_READ_VIA_NAME = re.compile(r"(?:environ|source|env)\.get\(\s*([A-Z][A-Z0-9_]*)\s*[,)]")
#: 모듈 수준 ``NAME = "ENV_VAR"``. 위 정규식이 잡은 이름을 실제 변수명으로 푼다.
_NAME_CONSTANT = re.compile(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([A-Z][A-Z0-9_]*)"\s*$', re.M)


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


_PROD_DB = _ROOT / "docker-compose.prod.db.yml"

#: db 서비스가 어느 키로 불리는가 — 분리 토폴로지 파일에서는 ``cubrid``다.
_DB_SERVICES = ((_DEV, "db"), (_PROD, "db"), (_PROD_DB, "cubrid"))


def _db_service(path: Path, name: str) -> dict:
    return _compose(path)["services"][name]


def test_every_db_healthcheck_passes_the_password():
    """🔴 healthcheck가 ``CUBRID_PASSWORD``를 넘긴다 (`#1058` 결정요청 §0-4).

    이미지는 첫 부트에 비밀번호를 걸지 않고, 배포가 브로커 기동 뒤
    ``ALTER USER dba PASSWORD``로 건다(``deploy.yml``). **그 순간부터 비밀번호 없는
    healthcheck는 실패한다** — 실측이다::

        csql -u dba pwtest -c "SELECT 1 FROM db_root"        → ERROR: Incorrect or
                                                               missing password. (exit 1)
        csql -u dba -p "s3cret" pwtest -c "SELECT 1 …"       → 1 row selected. (exit 0)

    ``csql``은 실패에 **종료 코드 1**을 내므로(실측) healthcheck가 그대로 unhealthy가
    되고, ``depends_on: service_healthy``에 걸린 앱은 영영 기다린다. 빈 값도 ``-p ""``로
    통과하므로 비밀번호를 걸기 전과 뒤가 같은 명령으로 돈다.
    """
    for path, name in _DB_SERVICES:
        service = _db_service(path, name)
        test = service["healthcheck"]["test"]
        joined = " ".join(test)
        assert "csql" in joined, f"{path.name}: healthcheck가 csql이 아니다 — {test}"
        assert "CUBRID_PASSWORD" in joined, (
            f"{path.name}: healthcheck에 CUBRID_PASSWORD가 없다 — 비밀번호를 건 뒤 "
            f"컨테이너가 영영 unhealthy가 된다: {test}"
        )
        # 컨테이너에 그 값이 들어가야 셸이 펼칠 수 있다. compose의 `environment:`와
        # `env_file:`만 컨테이너로 들어간다(이 파일 머리말의 `#508`과 같은 함정).
        assert "CUBRID_PASSWORD" in service.get("environment", {}), (
            f"{path.name}: db 서비스의 environment에 CUBRID_PASSWORD가 없다 — "
            f"healthcheck가 빈 값을 넘긴다."
        )


def test_db_healthchecks_go_through_a_shell():
    """``CMD``(exec 형식)는 셸을 거치지 않아 ``$CUBRID_PASSWORD``가 펼쳐지지 않는다.

    펼쳐지지 않으면 비밀번호 자리에 **여섯 글자 문자열 ``$CUBRID_PASSWORD``** 가
    들어가 언제나 실패한다 — 변수를 쓰기로 했으면 셸을 거쳐야 한다.
    """
    for path, name in _DB_SERVICES:
        test = _db_service(path, name)["healthcheck"]["test"]
        assert test[:3] == ["CMD", "sh", "-c"], f"{path.name}: 셸을 거치지 않는다 — {test}"


def test_db_healthchecks_do_not_hardcode_the_database_name():
    """DB 이름도 ``CUBRID_DB``를 쓴다 — 박아 두면 그 값을 바꿀 때 healthcheck만 없는 DB를 묻는다."""
    for path, name in _DB_SERVICES:
        joined = " ".join(_db_service(path, name)["healthcheck"]["test"])
        assert "CUBRID_DB" in joined, f"{path.name}: DB 이름이 박혀 있다 — {joined}"


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
        # CUBRID 브로커 포트다 (`#1058`). 종전 `@db:5432/`는 PostgreSQL 포트였다 —
        # 전환 뒤에도 그대로 남아 이 검사만 빨갛게 떠 있었다.
        assert "@db:33000/" in env["DATABASE_URL"], (
            f"{path.name}의 DATABASE_URL이 컨테이너 네트워크 주소를 가리키지 않는다: "
            f"{env['DATABASE_URL']}"
        )


def test_env_example_documents_every_variable_the_app_reads():
    """앱이 읽는 환경변수가 ``.env.example``에 전부 적혀 있다.

    본보기에 없는 변수는 **존재를 아는 방법이 없다.** ``.env``는 커밋되지 않으므로
    새로 합류한 사람이 참고할 수 있는 목록은 이 파일뿐이다.

    주석 처리된 줄(``# SMTP_HOST=...``)도 적힌 것으로 본다 — 선택 입력임을 그 형태로
    표현하고 있다.

    **이름을 상수에 담아 읽는 것도 센다 (#1290).** 종전에는 괄호 안이 리터럴일 때만
    셌고, 그래서 ``INITIAL_ADMIN_EMAILS``(``env.get(ENV_NAME)``)가 본보기 두 곳
    어디에도 없는 채로 이 검사를 통과했다 — 가드가 초록불인 채 비어 있었다.
    """
    src = _ROOT / "src"
    read: set[str] = set()
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        read |= set(_ENV_READ.findall(text))
        read |= set(_ENV_INDEX.findall(text))
        # 같은 모듈 안의 ``NAME = "ENV_VAR"``만 푼다. 모듈을 넘나드는 상수까지 쫓으려면
        # import를 해석해야 하고, 그 복잡도는 이 가드가 감당할 몫이 아니다 — 지금까지
        # 나온 사례는 전부 같은 모듈 안에 있다.
        names = dict(_NAME_CONSTANT.findall(text))
        read |= {names[ref] for ref in _ENV_READ_VIA_NAME.findall(text) if ref in names}

    example = _ENV_EXAMPLE.read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.M))

    missing = sorted(read - documented)
    assert not missing, (
        f".env.example에 없는 환경변수를 앱이 읽는다: {', '.join(missing)}. "
        "본보기에 없으면 그 변수의 존재를 아는 방법이 없다."
    )


def test_oci_app_compose_uses_every_variable_its_env_example_declares():
    """``.env.app.example``이 적는 값이 ``docker-compose.prod.app.yml``에서 실제로 쓰인다.

    ## 무엇을 막는가 (#1290)

    이 서비스에는 **``env_file:``이 없다.** 아래 ``environment:`` 목록에 적힌 키만
    컨테이너로 들어간다 — compose가 ``.env``를 읽는 것은 ``${VAR}`` **치환용**이지
    컨테이너 주입이 아니다. 그래서 본보기에만 있고 compose가 쓰지 않는 값은 **`.env`에
    정성껏 채워도 앱에 닿지 않는다.**

    ``INITIAL_ADMIN_EMAILS``(당시 이름 ``INITIAL_OFFICE_EMAILS``)가 정확히 그 상태였다.
    본보기에 행을 넣는 것만으로는
    배포가 고쳐지지 않는다 — 그 사실을 사람이 알아채는 경로가 없어서 검사로 만든다.

    `#508`이 개발·단일호스트 compose에서 같은 함정을 겪었고(``MAIL_BACKEND``가 닿지
    않아 **가입은 201인데 인증 메일이 오지 않았다**), 그때 만든 검사가
    :func:`test_dev_app_loads_env_file`·:func:`test_prod_app_loads_env_file`이다.
    **분리 토폴로지 파일만 그 검사 밖에 있었다.**

    ## 왜 「``environment:``에 있는가」가 아니라 「쓰이는가」인가

    본보기의 값 전부가 주입 대상인 것은 아니다 — ``CUBRID_HOST``·``CUBRID_PASSWORD``는
    ``x-cubrid-url`` 앵커에서 URL을 조립하는 데 쓰이고, ``BACKEND_IMAGE``는 ``image:``에
    쓰인다. 셋 다 컨테이너 환경변수로 들어가지 않는 것이 맞다. 공통 규칙은 **「compose
    어딘가에서 이 이름이 쓰인다」**이고, 그것이 깨질 때가 곧 「적어도 아무 일이 일어나지
    않는」 때다.
    """
    declared = set(
        re.findall(
            r"^#?\s*([A-Z][A-Z0-9_]*)=",
            _APP_ENV_EXAMPLE.read_text(encoding="utf-8"),
            re.M,
        )
    )
    compose = _PROD_APP.read_text(encoding="utf-8")

    unused = sorted(
        name
        for name in declared
        if f"${{{name}" not in compose and not re.search(rf"^\s*{name}:", compose, re.M)
    )
    assert not unused, (
        f".env.app.example이 적는데 docker-compose.prod.app.yml이 쓰지 않는 값: "
        f"{', '.join(unused)}. 이 서비스에는 env_file이 없어 environment 목록에 없으면 "
        "컨테이너에 닿지 않는다 — .env에 채워도 아무 일도 일어나지 않는다."
    )


def test_env_example_does_not_set_app_env():
    """``.env.example``이 ``APP_ENV``를 **설정하지 않는다** (#810).

    ## 무엇이 문제였나

    ``docker-compose.prod.yml``의 ``APP_ENV: ${APP_ENV:-production}``은 compose 변수
    치환이다. 치환은 셸 환경 다음으로 **저장소 루트의 ``.env``를 읽는다.** 그래서
    ``.env``에 ``APP_ENV=development``가 있으면 그 값이 ``:-production`` 기본값을
    이기고, 이미지에 굳어 있는 ``ENV APP_ENV=production``(``Dockerfile:85``)까지
    ``environment:``가 덮는다 — **프로덕션 스택이 development로 뜬다.**

    ``.env``가 운영 호스트에 없다는 가정은 성립하지 않는다. ``#524``가 프로덕션
    메일 설정(``MAIL_BACKEND=smtp``·``SMTP_HOST``)을 요구하고, ``#508``이 그 값을
    ``env_file: .env``로 컨테이너에 넣게 했다. **``.env``는 운영 설정 파일이기도 하다.**

    ## 왜 열리면 조용한가

    그 상태에서 앱은 정상 기동하고 ``/health``도 200이다. 함께 열리는 것은 다섯이다 —
    dev-login(미인증 세션 발급) · ``/docs`` · 데모 계정 시드(비밀번호가 ``README.md``에
    공개돼 있다) · DB URL 개발 기본값 폴백 · ``console`` 메일 백엔드.

    ## 왜 주석으로 두는가

    지우지 않는다. ``.env.example``은 **변수의 존재를 알리는 유일한 목록**이고
    (:func:`test_env_example_documents_every_variable_the_app_reads`가 그것을 강제한다),
    주석 처리된 줄도 그 목록에 든다. 개발에는 값이 필요 없다 — 미설정이 곧
    ``development``이며 ``docker-compose.yml``은 이 변수를 넘기지도 않는다.
    """
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    live = [line for line in text.splitlines() if re.match(r"^\s*APP_ENV\s*=", line)]

    assert not live, (
        f".env.example이 APP_ENV를 설정한다: {live}. "
        "이 파일을 그대로 .env로 복사하면 docker-compose.prod.yml의 "
        "${APP_ENV:-production} 치환이 그 값을 읽어 프로덕션 스택이 그 환경으로 뜬다. "
        "값이 필요하면 주석(`# APP_ENV=...`)으로 둔다 (#810)."
    )


def test_prod_app_does_not_publish_a_host_port():
    """프로덕션 ``app``이 호스트 포트를 열지 않는다 (#811).

    ## 무엇을 막는가

    종전에는 ``ports: ["8000:8000"]``이었다. 그러면 **nginx가 제공하는 보호가 전부
    우회 가능**하다 — ``X-Forwarded-For`` 덮어쓰기(``frontend/nginx.conf:24``) ·
    ``client_max_body_size`` · TLS 종단 · ``Host`` 검사.

    ## 왜 지금 특히 중요한가

    ``#786`` ⑵가 ``USE_FORWARDED_FOR=true``로 바꾸려 한다. 이 포트가 열린 채로 그것을
    켜면 공격자가 ``:8000``에 직접 붙어 ``X-Forwarded-For``를 위조해 **요청 한도를
    완전히 우회**한다 — 수정이 상황을 악화시킨다. 이 검사가 그 선행 조건을 고정한다.

    ## 개발 compose는 대상이 아니다

    ``docker-compose.yml``의 ``8000:8000``은 그대로 둔다. Vite dev 서버가 ``/api``를
    ``127.0.0.1:8000``으로 프록시하고(``#138``), ``scripts/demo_up.sh``도 그 주소를
    본다. 개발 스택 앞에는 nginx가 없으므로 우회할 보호도 없다.
    """
    service = _app_service(_PROD)

    assert "ports" not in service, (
        f"docker-compose.prod.yml의 app이 호스트 포트를 연다: {service.get('ports')}. "
        "nginx의 X-Forwarded-For 덮어쓰기·client_max_body_size·Host 검사가 "
        "전부 우회된다 (#811 · #786 ⑵의 선행 조건)."
    )
    # 열지 않는 것만으로 충분하지만, `expose`가 있어야 「깜빡 지웠다」와 구분된다.
    assert "8000" in {str(port) for port in service.get("expose", [])}, (
        "app에 expose: ['8000']이 없다 — 포트를 의도적으로 닫았음이 드러나지 않는다."
    )


def test_dev_app_mounts_every_document_the_cross_ref_guard_reads():
    """`tests/test_doc_cross_refs.py`가 읽는 정본이 전부 dev 컨테이너에 마운트돼 있다 (#1207).

    ## 무엇을 막는가

    문서 여덟 중 **`UIFLOW.md`만 빠져 있었다.** 그런데 그 가드의 `TARGETS` **첫 항목이
    `UIFLOW`**다 — 가드가 태어난 이유 자체가 *「`DESIGN_SYSTEM`이 존재한 적도 없는
    `UIFLOW` 절을 6종 참조하고 있었다」*(`#583`)이다. **컨테이너 안에서는 그 검사가
    성립하지 않았다.**

    ## 왜 조용한가

    빠진 파일은 `FileNotFoundError`로 죽지만, 그것은 **컨테이너에서 pytest를 돌릴 때만**
    난다. 호스트에서 돌리면 파일이 제자리에 있어 초록으로 통과하므로, 어긋났다는 사실이
    드러나는 경로가 사실상 없다 — 컨테이너에서 한 번 돌려 본 사람이 있어야 한다.

    ## 왜 `TARGETS`를 읽어 오는가

    목록을 여기 베껴 두면 **두 곳이 갈리는 것을 막으려다 갈릴 자리를 하나 더 만든다.**
    정본을 늘리는 사람은 `TARGETS`에 행을 넣지 이 파일을 열지 않는다.

    `README.md`도 마운트돼 있지만 `TARGETS`에는 없다 — 그쪽은 참조 **대상**이 아니라
    참조를 **하는** 쪽이다. 그래서 「`TARGETS` ⊆ 마운트」로만 본다.
    """
    from test_doc_cross_refs import TARGETS

    documents = set(TARGETS.values())
    mounts = _app_service(_DEV).get("volumes", [])
    mounted = {entry.split(":", 1)[0].removeprefix("./"): entry for entry in mounts}

    missing = sorted(documents - set(mounted))
    assert not missing, (
        f"docker-compose.yml의 app이 마운트하지 않는 정본 {len(missing)}개: "
        f"{', '.join(missing)}. tests/test_doc_cross_refs.py가 이 파일들을 읽으므로 "
        "컨테이너 안에서는 「파일 없음」으로 죽는다 (#1207)."
    )

    # 읽기 전용인지도 함께 본다 — 컨테이너가 정본을 고쳐 쓸 이유가 없다.
    writable = sorted(mounted[name] for name in documents if not mounted[name].endswith(":ro"))
    assert not writable, f"정본이 쓰기 가능하게 마운트돼 있다: {writable}"


def test_dev_app_still_publishes_8000():
    """개발 compose는 ``8000:8000``을 유지한다 (#811).

    `#811`이 프로덕션 쪽만 닫았다는 것을 고정한다. 개발 쪽까지 닫으면 Vite dev 서버의
    ``/api`` 프록시(``#138``)와 ``scripts/demo_up.sh``의 health 확인이 함께 죽는다 —
    그 실패는 「화면은 뜨는데 데이터가 안 온다」로 나타나 원인을 찾기 어렵다.
    """
    ports = {str(port) for port in _app_service(_DEV).get("ports", [])}

    assert "8000:8000" in ports, f"개발 compose의 app이 8000을 열지 않는다: {ports}"


# ── OCI 분리 토폴로지의 두 구멍 (#1331) ─────────────────────────────────────────
#
# `docker-compose.prod.app.yml`이 `SMTP_PORT`를 **빈 값으로** 넘겨 smtp로 바꾸는 순간
# 기동이 실패했고, `LOG_FILE`이 없어 `docs/OPERATIONS.md §8.2.1`의 장애 대응 절차가
# 「No such file」로 끝났다. 둘 다 **단일 호스트 compose에는 있었다** — 분리 토폴로지
# 파일만 빠져 있어서, 읽는 사람이 「문서대로 했는데 안 된다」에 도달한다.


def _prod_app_environment() -> dict[str, str]:
    """`prod.app.yml` backend 서비스의 `environment:` 매핑."""
    parsed = yaml.safe_load(_PROD_APP.read_text(encoding="utf-8"))
    return parsed["services"]["backend"]["environment"]


def test_prod_app_gives_smtp_port_a_default():
    """빈 값이 아니라 **587**을 넘긴다 (#1331).

    `${SMTP_PORT:-}`이면 `.env`에 값이 없을 때 compose가 **빈 문자열**을 넘기고, 앱은
    키가 있는 것으로 보아 기본값을 쓰지 않는다 — `int("")`로 기동이 실패한다. 사용자는
    「비워 두면 587」로 읽는데 실제로는 재시작 루프였다(`#787` 전환 때 밟는 길이다).
    """
    value = _prod_app_environment()["SMTP_PORT"]

    assert value == "${SMTP_PORT:-587}", (
        f"SMTP_PORT를 {value!r}로 넘긴다 — 빈 값이면 mail/config.py가 int('')로 터진다."
    )


def test_prod_app_writes_the_structured_log_file():
    """`LOG_FILE`과 로그 볼륨이 있다 (#1331 · `#827` ⑵).

    `docs/OPERATIONS.md §8.2.1`이 *「프로덕션 compose가 `LOG_FILE=/app/logs/api.jsonl`을
    설정한다」*고 적고 app-01에서 `docker exec cii-backend … /app/logs/api.jsonl`을
    지시하는데, **그 컨테이너를 만드는 것이 이 파일이다.** 없으면 장애 때 문서대로
    grep해도 파일이 없고, 컨테이너를 다시 만들면 콘솔 로그마저 사라진다.
    """
    parsed = yaml.safe_load(_PROD_APP.read_text(encoding="utf-8"))
    backend = parsed["services"]["backend"]

    log_file = backend["environment"].get("LOG_FILE")
    assert log_file, "prod.app.yml에 LOG_FILE이 없다 — OPERATIONS §8.2.1 절차를 쓸 수 없다."

    mounts = backend.get("volumes") or []
    log_dir = log_file.rsplit("/", 1)[0]
    assert any(str(mount).endswith(f":{log_dir}") for mount in mounts), (
        f"{log_dir}에 볼륨이 붙어 있지 않다 — 컨테이너를 다시 만들면 로그가 사라진다. "
        f"현재 volumes={mounts}"
    )

    # 호스트 경로 바인드가 아니라 **이름 있는 볼륨**이어야 한다 — 호스트 경로는 app-01의
    # 디렉터리 구조를 전제하고, 이름 있는 볼륨은 docker가 관리해 재생성에도 남는다.
    named = {
        str(mount).split(":", 1)[0]
        for mount in mounts
        if not str(mount).startswith(("/", ".", "~"))
    }
    declared = set(parsed.get("volumes") or {})
    assert named & declared, (
        f"로그 볼륨이 최상위 volumes에 선언돼 있지 않다. mounts={mounts} volumes={sorted(declared)}"
    )


def test_operations_log_path_matches_the_compose_file():
    """문서가 적는 경로와 compose가 넘기는 경로가 **같다** (#1331).

    둘이 갈리면 장애 대응 절차가 조용히 빗나간다 — 문서는 `api.jsonl`을 보라는데 파일은
    다른 이름으로 쌓인다.
    """
    log_file = _prod_app_environment()["LOG_FILE"]
    operations = (_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    assert log_file in operations, f"OPERATIONS.md에 {log_file}이 없다 — 문서와 compose가 갈렸다."


def test_deploy_renders_app_env_with_staging_default():
    """자동 배포가 ``APP_ENV``를 ``.env``에 렌더링한다 (기본 ``staging`` · #1201).

    2026-09-20 첫 자동 배포가 헬스 체크에서 죽었다 — ``deploy.yml``은 ``APP_ENV``를
    렌더하지 않았고, compose의 ``${APP_ENV:-production}`` 기본값으로 앱이
    ``production``으로 떴다. 수동 배포(§3.3)는 ``.env``에 ``APP_ENV=staging``을
    적어 둔 상태라 이 문제가 없었다. SMTP 시크릿이 없는 동안 ``MAIL_BACKEND``의
    기본값은 ``console``이어야 한다(``staging``·``production`` 어느 쪽이든
    ``smtp``+``SMTP_HOST`` 없음은 기동이 선다 — `mail/config.py`).
    """
    workflow = (_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

    assert "APP_ENV: ${{ secrets.APP_ENV || 'staging' }}" in workflow, (
        "deploy.yml이 APP_ENV 시크릿을 staging 기본으로 읽지 않는다 — "
        "비워 둔 채 production으로 떨어져 SMTP 없는 배포가 기동에서 죽는다 (#1201 · §4.5)."
    )
    # `#1634` 뒤로 `.env`는 러너의 `emit`이 만든다(종전 원격 heredoc의 `APP_ENV=${APP_ENV}`).
    assert 'emit APP_ENV "${APP_ENV}"' in workflow, (
        "deploy.yml이 .env에 APP_ENV를 렌더링하지 않는다."
    )
    assert "MAIL_BACKEND:-console" in workflow, (
        "MAIL_BACKEND 기본값이 console이 아니다 — SMTP_HOST 없이 smtp 기본이면 "
        "staging에서도 기동이 선다(#524 가드의 역방향)."
    )
    assert "MAIL_BACKEND:-smtp" not in workflow


#: `deploy.yml`이 읽는 시크릿 이름. `${{ secrets.NAME }}`.
_WORKFLOW_SECRET = re.compile(r"secrets\.([A-Z][A-Z0-9_]*)")

#: `OPERATIONS.md §5` 표의 첫 칸 — ``| `NAME` | 설명 |``.
_DOCUMENTED_SECRET = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|", re.M)


def test_deploy_secrets_are_listed_in_the_operations_secret_tables():
    """`deploy.yml`이 요구하는 시크릿이 `OPERATIONS.md §5` **표에** 있다.

    ## 같은 자리에서 세 번 섰다

    | 건 | 증상 |
    |---|---|
    | `#1201` | 필수 9종 미등록 — `deploy-db`가 가드에서 즉시 실패, 누적 7회 |
    | `#1479` | `CLOUDFLARE_API_TOKEN` 미등록 — `deploy-frontend` 8회 연속 실패 |
    | `#1496` | `API_ORIGIN` 미등록 — `deploy-frontend`가 자리표시자 검사에서 정지 |

    셋 다 **워크플로는 값을 요구하는데 등록 목록에는 그 이름이 없었다.**

    ## 산문에 있는 것으로는 부족하다

    `API_ORIGIN`은 `§3.5` 본문에 설명까지 붙어 있었지만 **`§5` 표에는 없었다.** 시크릿을
    등록하는 사람이 여는 것은 `§5`이고, 거기 없는 이름은 **등록되지 않는다.** 그래서 이
    검사는 산문이 아니라 **표의 첫 칸**만 본다.

    ``GITHUB_TOKEN``은 Actions가 자동으로 주입하므로 뺀다.
    """
    workflow = (_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    operations = (_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    start = operations.index("## 5. GitHub Actions 시크릿")
    section = operations[start : operations.index("## 6. ", start)]
    documented = set(_DOCUMENTED_SECRET.findall(section))
    required = set(_WORKFLOW_SECRET.findall(workflow)) - {"GITHUB_TOKEN"}

    missing = sorted(required - documented)
    assert not missing, (
        f"deploy.yml이 쓰는데 OPERATIONS.md §5 표에 없는 시크릿: {missing}. "
        "등록하는 사람은 §5 표를 보고 움직인다 — 표에 없으면 등록되지 않고, "
        "배포는 그 시크릿을 읽는 잡에서 선다 (#1201 · #1479 · #1496)."
    )
