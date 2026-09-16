"""실행 단위 잠금 — 스위트 두 개가 같은 테스트 DB를 겹쳐 쓰지 못한다 (#894).

2026-09-09에 로컬에서 스위트를 겹쳐 돌려 **220 failed · 30 errors**가 났고, 마지막에는
테스트 DB가 중간 리비전에 남아 다시 만들어야 했다. 실패 수가 원인을 가렸다 — 「내 수정이
크게 깨뜨렸다」로 읽혔지 병렬 실행을 의심하기 어려웠다.

여기서 잠그는 것은 셋이다.

1. 스위트가 도는 동안 **잠금을 쥐고 있다**
2. 두 번째 실행은 **원인을 말하며 즉시 멈춘다** — 실제로 두 번째 `pytest`를 띄워 본다
3. `upgrade head`가 실패하면 **DB가 남은 리비전과 복구 방법**을 알린다

CI는 잡마다 새 DB에서 한 번만 돌리므로 잠금이 늘 잡힌다 — 동작이 달라지지 않는다.

⚠️ **CUBRID 전환으로 이 잠금이 no-op이 되었다** (`#1058`).

`tests/conftest.py`의 `_hold_suite_lock()`이 「CUBRID에는 advisory lock이 없으므로
no-op」으로 바뀌었다. 안내 문구(`SUITE_LOCK_MESSAGE`)는 파일에 남았는데 **잠그는 코드만
사라졌다** — 위 1·2를 검사할 대상이 없다.

이 파일은 종전에 `asyncpg`를 직접 import했는데 그 의존성도 빠져
(`ModuleNotFoundError: No module named 'asyncpg'`), **pytest 수집이 통째로 중단되어
2,399건이 한 건도 실행되지 않고 있었다.** 그래서 import를 걷어내고 1·2는 **사유를 적어
skip**한다 — 조용히 지우면 잠금이 사라진 사실까지 함께 사라진다.

**대체 수단을 정해야 한다**(`#1058` 후속): CUBRID에는 advisory lock이 없으므로
⑴ 잠금 테이블 한 행으로 대신할지 ⑵ 파일 잠금으로 갈지 ⑶ 겹쳐 쓰기를 감수할지.
겹쳐 돌리면 2026-09-09처럼 **220 failed**가 나고 원인이 가려진다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import TEST_DATABASE_URL, _upgrade_failure_message

_ROOT = Path(__file__).resolve().parents[1]

#: 잠금이 되살아나면 이 표시를 걷어낸다 — 걷어내는 순간 아래 두 검사가 다시 돈다.
_LOCK_IS_A_NOOP = pytest.mark.skip(
    reason="#1058 — CUBRID에는 advisory lock이 없어 `_hold_suite_lock()`이 no-op이다. "
    "대체 수단을 정한 뒤 이 표시를 걷어낸다."
)


@_LOCK_IS_A_NOOP
async def test_the_running_suite_holds_the_lock(migrated_db):
    """다른 연결은 잠금을 잡지 못한다 — 이 스위트가 쥐고 있다."""
    raise AssertionError("잠금 대체 수단이 정해지면 그 수단으로 다시 쓴다")


@_LOCK_IS_A_NOOP
def test_a_second_run_stops_and_says_why(migrated_db):
    """두 번째 `pytest`는 **잠금 메시지로 즉시 멈춘다** — 220건 실패가 아니라.

    같은 파일의 첫 검사를 자식 프로세스로 돌린다. 부모(지금 이 스위트)가 잠금을 쥐고
    있으므로 자식은 DB를 여는 첫 fixture에서 멈춰야 한다.
    """
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_suite_lock_db.py::test_the_running_suite_holds_the_lock",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
        timeout=180,
    )

    output = child.stdout + child.stderr
    assert child.returncode == 3, output
    assert "다른 pytest 실행이 이 테스트 DB를 쓰고 있습니다" in output
    # 원인을 말하는 대신 검사들이 줄줄이 실패하는 것이 이 이슈의 증상이었다.
    assert "failed" not in output.lower().split("다른 pytest")[0]


def test_upgrade_failure_names_the_revision_and_the_way_back(migrated_db):
    """`upgrade head`가 실패하면 **어느 리비전에 남았는지와 복구 방법**을 말한다.

    왕복 검사가 중간에 끊기면 DB가 중간 리비전에 남는데, alembic 원문만으로는 그 사실이
    읽히지 않았다.
    """
    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")

    message = _upgrade_failure_message(failed)

    assert "리비전" in message
    assert "test_zz_roundtrip.py" in message
    assert "테스트 DB 복구" in message
    assert "boom" in message  # alembic 원문도 함께 남긴다
