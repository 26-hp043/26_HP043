"""이슈 #1475 · 배포가 렌더하는 `.env`가 **compose가 쓰는 값을 빠뜨리지 않는지** 고정한다.

## 체인은 세 고리인데 검사는 둘까지만 있었다

```
.env.app.example  →  docker-compose.prod.app.yml  →  .github/workflows/deploy.yml 의 `.env` 렌더
└──── test_compose_env_wiring.py 가 본다 (#1290) ────┘   └─────── 아무도 보지 않았다 ───────┘
```

`#1290`이 첫 고리를 메우고 멈췄다. 그 결과 `INITIAL_ADMIN_EMAILS`가 **본보기에도 있고
compose의 `environment:`에도 있는데** 배포가 `.env`에 쓰지 않아 **항상 빈 값**이었다.

## 왜 조용한가

`deploy.yml`은 `.env`를 `cat > .env`로 **통째로 덮어쓴다.** 그래서 app-01에 손으로 적어
두어도 **다음 배포가 지운다** — 「적어 뒀는데 아무 일도 없다」가 되는 자리이며, `#508`·
`#1290`·`#1331`이 각각 다른 변수에서 겪은 것과 같은 종류다.

그리고 증상이 환경에 따라 다르다.

| `APP_ENV` | `INITIAL_ADMIN_EMAILS`가 빌 때 |
|---|---|
| `production` | 기동 거부 — 배포 로그에 **빨갛게 남는다** |
| `staging` | **조용히 뜬다. 관리자 0명으로** |

배포본은 `staging`이다(`deploy.yml`의 `${{ secrets.APP_ENV || 'staging' }}` · `#1478`).
즉 **더 조용한 쪽**으로 떨어져 있었다 — `role_bootstrap` 독스트링이 *「`staging`에는 이
가드가 없다 … 사람이 값을 채웠는지 직접 봐야 한다」*로 미리 적어 둔 상태다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_PROD_APP = _ROOT / "docker-compose.prod.app.yml"
_APP_ENV_EXAMPLE = _ROOT / ".env.app.example"

#: 렌더에 없어도 되는 값 — compose가 **안전한 기본값**을 자기 쪽에 들고 있는 것들.
#:
#: `LOG_FILE`·`RATE_LIMIT_*`·`USE_FORWARDED_FOR`처럼 본보기에 없는 값은 애초에 아래
#: 대조 대상이 아니다. 이 집합은 **본보기에 있으면서도** 렌더에서 빼는 것을 적는 자리이며,
#: 지금은 비어 있다 — 빠뜨려도 되는 값이 있으면 **여기에 사유와 함께** 적는다.
_RENDER_EXEMPT: frozenset[str] = frozenset()


def _rendered_keys() -> set[str]:
    """app-01 `.env` 렌더가 쓰는 키.

    `#1634` 뒤로 `.env`는 러너가 `{ emit KEY "값"; … } > "${RUNNER_TEMP}/app.env"`로
    만든다(종전에는 원격의 `cat > .env <<EOF` heredoc). db-01에도 같은 모양의 블록이
    있으므로(`db.env` · `CUBRID_PASSWORD` 한 줄) **`app.env`로 끝나는 블록**을 고른다.
    """
    lines = _DEPLOY.read_text(encoding="utf-8").splitlines()
    ends = [i for i, line in enumerate(lines) if '} > "${RUNNER_TEMP}/app.env"' in line]
    assert len(ends) == 1, "deploy.yml에서 app-01 `.env` 렌더 블록을 찾지 못했다."
    end = ends[0]
    start = next(i for i in range(end - 1, -1, -1) if lines[i].strip() == "{")
    return {
        m.group(1)
        for line in lines[start + 1 : end]
        if (m := re.match(r"\s*emit ([A-Z][A-Z0-9_]*) ", line))
    }


def _example_keys() -> set[str]:
    text = _APP_ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, re.M))


def test_deploy_renders_every_value_the_compose_substitutes():
    """🔴 본보기에 있고 compose가 `${...}`로 치환하는 값은 **배포 렌더에도 있다** (#1475).

    빠지면 compose가 빈 문자열을 넘기고, 그 사실이 **어디에도 드러나지 않는다.**
    """
    compose = _PROD_APP.read_text(encoding="utf-8")
    rendered = _rendered_keys()

    missing = sorted(
        name for name in _example_keys() - rendered - _RENDER_EXEMPT if f"${{{name}" in compose
    )
    assert not missing, (
        f"`.env.app.example`에 있고 compose가 치환하는데 deploy.yml의 `.env` 렌더에 없는 값: "
        f"{', '.join(missing)}. compose가 빈 문자열을 넘기고, app-01의 `.env`에 손으로 적어도 "
        "`cat > .env`가 다음 배포에서 지운다 (#1475)."
    )


def test_initial_admin_emails_reaches_the_container():
    """🔴 `INITIAL_ADMIN_EMAILS`가 **세 고리 전부**에 있다 (#1475 · #672 · #1301).

    이 값이 비면 새 DB는 **관리자 0명**으로 뜨고, 역할을 올리는 경로가 관리자 전용이라
    **화면으로는 아무도 풀 수 없다.** 위 일반 검사가 이미 덮지만, 이 변수는 빠졌을 때의
    대가가 커서 이름을 박아 따로 고정한다 — 일반 검사가 느슨해져도 이쪽은 남는다.
    """
    name = "INITIAL_ADMIN_EMAILS"

    assert name in _example_keys(), f".env.app.example에 {name}이 없다."
    assert f"${{{name}" in _PROD_APP.read_text(encoding="utf-8"), (
        f"docker-compose.prod.app.yml의 environment에 {name}이 없다 — 이 서비스에는 "
        "env_file이 없어 목록에 없으면 컨테이너에 닿지 않는다 (#1290)."
    )
    assert name in _rendered_keys(), (
        f"deploy.yml의 `.env` 렌더에 {name}이 없다 — 배포가 `.env`를 덮어쓰므로 "
        "손으로 적어 둔 값도 사라진다 (#1475)."
    )


def test_legacy_initial_office_emails_is_not_rendered():
    """옛 이름 `INITIAL_OFFICE_EMAILS`를 **렌더하지 않는다** (#1301).

    그 값이 비어 있지 않으면 앱이 **환경과 무관하게 기동을 거부한다**
    (`auth/role_bootstrap.py`). 이름이 바뀐 것을 그 자리에서 알리려는 장치이므로,
    배포가 빈 값이라도 써 두면 조용히 지나갈 뿐 도움이 되지 않는다.
    """
    assert "INITIAL_OFFICE_EMAILS" not in _rendered_keys(), (
        "deploy.yml이 옛 이름 INITIAL_OFFICE_EMAILS를 렌더한다 — 이름이 바뀐 것을 "
        "알리는 기동 거부가 무의미해진다 (#1301)."
    )


def _db_rendered_keys() -> set[str]:
    """db-01 `.env` 렌더가 쓰는 키 — 러너의 `db.env` `emit` 블록 (:func:`_rendered_keys`의 짝)."""
    lines = _DEPLOY.read_text(encoding="utf-8").splitlines()
    ends = [i for i, line in enumerate(lines) if '} > "${RUNNER_TEMP}/db.env"' in line]
    assert len(ends) == 1, "deploy.yml에서 db-01 `.env` 렌더 블록을 찾지 못했다."
    end = ends[0]
    start = next(i for i in range(end - 1, -1, -1) if lines[i].strip() == "{")
    return {
        m.group(1)
        for line in lines[start + 1 : end]
        if (m := re.match(r"\s*emit ([A-Z][A-Z0-9_]*) ", line))
    }


def test_deploy_db_renders_every_value_the_db_compose_substitutes():
    """🔴 db-01 렌더도 같다 — compose가 `${…}`로 치환하는 값은 **세 고리 전부**에 있다 (#1641).

    `OCI_DB_PRIVATE_IP`가 그 값이다. compose가 CUBRID 게시를 이 주소에만 붙이므로
    (`docker-compose.prod.db.yml` `ports`), 고리 하나가 끊기면 두 가지 중 하나다 —
    치환이 필수라 **배포가 선다**(그나마 낫다), 아니면 빈 값으로 **모든 인터페이스에
    열린다.** 고리는 셋이다.

    1. 잡의 ``env:``가 시크릿을 읽는다
    2. 러너의 ``emit`` 블록(``db.env``)이 그 이름을 **잡 env의 값으로** 쓴다 (#1634 — 종전에는
       ``ssh … "NAME='${NAME}' … bash -s"`` + 원격 ``cat > .env`` heredoc)
    3. ``OCI_DB_PRIVATE_IP``는 ssh로도 넘긴다 — 원격의 게시 주소 확인(#1867)이 직접 쓴다
    """
    compose = (_ROOT / "docker-compose.prod.db.yml").read_text(encoding="utf-8")
    workflow = _DEPLOY.read_text(encoding="utf-8")
    substituted = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    rendered = _db_rendered_keys()

    missing = sorted(substituted - rendered)
    assert not missing, (
        f"docker-compose.prod.db.yml이 치환하는데 deploy.yml의 db-01 `.env` 렌더에 없는 값: "
        f"{', '.join(missing)}. compose가 빈 문자열을 넘기고, db-01의 `.env`에 손으로 적어도 "
        "배포가 `.env`를 통째로 다시 쓰므로 다음 배포에서 지워진다 (#1641 · #1475)."
    )

    # 깜빡 지운 시크릿을 쓰면 안 되므로 db-01 잡 구간(`deploy-db:` ~ `deploy-app:`)만 본다.
    job = workflow[workflow.index("\n  deploy-db:") : workflow.index("\n  deploy-app:")]
    for name in sorted(substituted):
        assert f"{name}: ${{{{ secrets.{name} }}}}" in job, (
            f"deploy-db 잡의 env가 시크릿 {name}을 읽지 않는다 — 렌더 줄이 빈 값을 적는다."
        )
        assert f'emit {name} "${{{name}}}"' in job, (
            f"deploy-db의 `emit`이 잡 env의 {name}을 쓰지 않는다 — 렌더 줄이 빈 값을 적는다."
        )
    # 원격의 게시 주소 확인(#1867)은 `.env`가 아니라 셸 변수로 이 값을 읽는다.
    assert "OCI_DB_PRIVATE_IP='${OCI_DB_PRIVATE_IP}'" in job, (
        "deploy-db가 ssh 원격 셸에 OCI_DB_PRIVATE_IP를 넘기지 않는다 — 게시 주소 확인이 "
        "빈 값과 비교해 배포가 선다."
    )
