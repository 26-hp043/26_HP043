"""이슈 #1485 · 배포가 데모 데이터를 **수동 트리거로만** 적재하는지 고정한다.

## 무엇을 막는가

배포본에 **선박이 0척**이었다(2026-09-21 실측 — `GET /api/v1/vessels` → `data: []`).
원인은 환경 가드가 아니라 **호출 누락**이다: `deploy.yml`이 `python -m cii_platform.db.seed`
(규제 파라미터)만 부르고 `demo_seed`를 한 번도 부르지 않았다.

> ⚠️ 「데모 데이터는 `development`·`test`에서만 적재된다」는 설명은 **틀렸다.**
> `demo_seed.seed_demo()`는 환경을 보지 않는다. 환경 가드는 `seed_demo_user()`
> (시연 계정) 한 항목 **안에만** 있다.

## 왜 자동이 아니라 수동인가

`db/demo_seed.py` 머리주석이 경계를 적는다 — *「이 모듈의 데이터는 **시연·개발 편의**이며
운영 데이터가 아니다. 그래서 마이그레이션 체인에 넣지 않고 필요할 때만 부른다」*.
매 배포마다 돌리면 그 경계가 사라지고, `production` 전환 뒤에도 조건이 남는다.

## 왜 조용한가

조건을 지워 **무조건 실행**으로 바꿔도 배포는 성공하고 `/health`도 200이다. 데모 데이터가
운영 데이터에 섞이는 것은 화면을 열어 봐야 드러나며, 그때는 이미 들어간 뒤다. 반대로
호출을 통째로 지우면 **다시 선박 0척**으로 돌아가는데 그것도 배포 로그에 실패로 남지 않는다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_DEMO_SEED = _ROOT / "src" / "cii_platform" / "db" / "demo_seed.py"

_MODULE = "cii_platform.db.demo_seed"


def _deploy_text() -> str:
    return _DEPLOY.read_text(encoding="utf-8")


def test_deploy_can_seed_demo_data():
    """배포가 데모 시드를 **부를 수 있다** (#1485).

    이 호출이 없으면 배포본은 규제 파라미터만 받고 선박이 0척으로 남는다.

    ⚠️ **모듈 이름이 파일 어딘가에 있는지로 보지 않는다.** ``--clear`` 호출에도 같은
    이름이 들어 있어, 적재 호출만 지우고 초기화 호출을 남겨도 통과했다 — 그 상태는
    **행을 지울 줄만 알고 넣을 줄은 모르는 배포**이고, 증상은 「다시 선박 0척」이다.
    돌연변이 검사가 실제로 그렇게 빠져나갔다. 그래서 **``--clear``가 없는 호출**을 센다.
    """
    seeding = [
        line for line in _deploy_text().splitlines() if _MODULE in line and "--clear" not in line
    ]

    assert seeding, (
        f"deploy.yml에 {_MODULE} **적재** 호출이 없다 — 배포본에 선박이 한 척도 "
        "들어가지 않는다. (--clear 호출만 있는 것은 적재가 아니다.) (#1485)"
    )


def test_demo_seed_is_behind_a_manual_input():
    """데모 시드 호출이 **조건 안**에 있다 (#1485).

    무조건 실행으로 바뀌면 시연용 데이터가 매 배포마다 운영 DB에 들어간다 —
    `db/demo_seed.py`가 「운영 데이터가 아니다」로 그은 경계를 지우는 것이다.
    """
    text = _deploy_text()

    # `workflow_dispatch` 입력이 있어야 사람이 켤 수 있다.
    assert re.search(r"^\s+seed_demo:", text, re.M), (
        "workflow_dispatch에 seed_demo 입력이 없다 — 켤 방법이 없다 (#1485)."
    )
    assert re.search(r"^\s+SEED_DEMO:\s*\$\{\{\s*inputs\.seed_demo\s*\}\}", text, re.M), (
        "SEED_DEMO가 inputs.seed_demo에서 오지 않는다 (#1485)."
    )

    # 호출부가 `SEED_DEMO`를 보는 `if` 안에 있어야 한다.
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _MODULE in line and "--clear" not in line:
            guard = _enclosing_shell_guard(text, line_no, "SEED_DEMO")
            assert guard, (
                f"deploy.yml:{line_no}의 데모 시드 호출이 SEED_DEMO 조건 밖에 있다 — "
                "매 배포마다 시연 데이터가 적재된다 (#1485)."
            )


def test_clear_demo_is_behind_its_own_input():
    """초기화도 별도 입력 뒤에 있다 (#1485).

    `--clear`는 행을 지운다. `seed_demo`와 같은 스위치에 묶으면 **적재하려다 지운다.**
    """
    text = _deploy_text()

    assert re.search(r"^\s+clear_demo:", text, re.M), (
        "workflow_dispatch에 clear_demo 입력이 없다 (#1485)."
    )
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _MODULE in line and "--clear" in line:
            guard = _enclosing_shell_guard(text, line_no, "CLEAR_DEMO")
            assert guard, (
                f"deploy.yml:{line_no}의 --clear 호출이 CLEAR_DEMO 조건 밖에 있다 — "
                "배포마다 데모 데이터를 지운다 (#1485)."
            )
            break
    else:  # pragma: no cover - 위 루프가 반드시 찾는다
        raise AssertionError("deploy.yml에 --clear 호출이 없다 (#1485).")


def _enclosing_shell_guard(text: str, line_no: int, var: str) -> bool:
    """``line_no`` 위쪽에서 ``var``를 보는 ``if``가 ``fi`` 없이 열려 있는가.

    셸 조건은 들여쓰기로 표현되지 않아 구문 분석이 어렵다. 그래서 **거슬러 올라가며**
    가장 가까운 `if`/`fi`를 본다 — 데모 시드 호출 바로 위 몇 줄 안에 있으므로 이것으로
    충분하고, 조건을 지우는 돌연변이를 실제로 잡는다(`#1485` 돌연변이 검사).
    """
    lines = text.splitlines()
    for prev in reversed(lines[: line_no - 1]):
        stripped = prev.strip()
        if stripped.startswith("fi"):
            return False
        if stripped.startswith("if ") and var in stripped:
            return True
        if stripped.startswith("if "):
            return False
    return False


def test_demo_seed_module_exposes_clear():
    """``--clear`` 진입점이 있다 (#1485).

    적재는 **덮어쓰지 않는다**(`_insert_ignoring_existing`이 `IntegrityError`를 삼킨다).
    그런데 시드 시각은 **적재일 기준 상대값**이라(`#792`) 오래된 적재는 진행 중 항차가
    도착 예정을 넘긴 상태로 보인다 — 다시 넣어서는 되돌릴 수 없고 지우고 넣어야 한다.

    종전에는 `clear_demo()`가 함수로만 있어 배포본에서 초기화하려면 `force_db_init`
    (볼륨 파괴, 비가역)밖에 없었다.
    """
    source = _DEMO_SEED.read_text(encoding="utf-8")

    assert '"--clear"' in source, (
        "demo_seed.py의 진입점에 --clear가 없다 — 배포본에서 데모 데이터를 지울 방법이 "
        "볼륨 파괴(force_db_init)뿐이 된다 (#1485)."
    )
    assert "clear_demo(conn)" in source, "--clear가 clear_demo를 부르지 않는다 (#1485)."
