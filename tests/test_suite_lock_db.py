"""실행 단위 잠금 — 스위트 두 개가 같은 테스트 DB를 겹쳐 쓰지 못한다 (#894).

2026-09-09에 로컬에서 스위트를 겹쳐 돌려 **220 failed · 30 errors**가 났고, 마지막에는
테스트 DB가 중간 리비전에 남아 다시 만들어야 했다. 실패 수가 원인을 가렸다 — 「내 수정이
크게 깨뜨렸다」로 읽혔지 병렬 실행을 의심하기 어려웠다.

여기서 잠그는 것은 셋이다.

1. 스위트가 도는 동안 **잠금을 쥐고 있다**
2. 두 번째 실행은 **원인을 말하며 즉시 멈춘다** — 실제로 두 번째 `pytest`를 띄워 본다
3. `upgrade head`가 실패하면 **DB가 남은 리비전과 복구 방법**을 알린다

CI는 잡마다 새 DB에서 한 번만 돌리므로 잠금이 늘 잡힌다 — 동작이 달라지지 않는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import asyncpg
from conftest import (
    SUITE_LOCK_KEY,
    TEST_DATABASE_URL,
    _plain_dsn,
    _upgrade_failure_message,
)

_ROOT = Path(__file__).resolve().parents[1]


async def test_the_running_suite_holds_the_lock(migrated_db):
    """다른 연결은 잠금을 잡지 못한다 — 이 스위트가 쥐고 있다."""
    other = await asyncpg.connect(_plain_dsn(TEST_DATABASE_URL))
    try:
        assert await other.fetchval("SELECT pg_try_advisory_lock($1)", SUITE_LOCK_KEY) is False
    finally:
        await other.close()


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
