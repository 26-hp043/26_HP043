"""실행 단위 잠금 — 스위트 두 개가 같은 테스트 DB를 겹쳐 쓰지 못한다 (#894).

2026-09-09에 로컬에서 스위트를 겹쳐 돌려 **220 failed · 30 errors**가 났고, 마지막에는
테스트 DB가 중간 리비전에 남아 다시 만들어야 했다. 실패 수가 원인을 가렸다 — 「내 수정이
크게 깨뜨렸다」로 읽혔지 병렬 실행을 의심하기 어려웠다.

여기서 잠그는 것은 셋이다.

1. 스위트가 도는 동안 **잠금을 쥐고 있다**
2. 두 번째 실행은 **원인을 말하며 즉시 멈춘다** — 실제로 두 번째 `pytest`를 띄워 본다
3. `upgrade head`가 실패하면 **DB가 남은 리비전과 복구 방법**을 알린다

CI는 잡마다 새 DB에서 한 번만 돌리므로 잠금이 늘 잡힌다 — 동작이 달라지지 않는다.

⚠️ **CUBRID 전환에서 이 잠금이 한동안 사라져 있었다** (`#1058` → `#1250`).

`tests/conftest.py`의 `_hold_suite_lock()`이 「CUBRID에는 advisory lock이 없으므로
no-op」으로 바뀌어 있었다. 안내 문구(`SUITE_LOCK_MESSAGE`)는 파일에 남았는데 **잠그는
코드만 사라져** 위 1·2를 검사할 대상이 없었다. 이 파일은 종전에 `asyncpg`를 직접
import했는데 그 의존성도 빠져, **pytest 수집이 통째로 중단되어 2,399건이 한 건도
실행되지 않던** 시기도 있었다.

**대체 수단은 파일 잠금(`flock`)이다** — 그 시절 적어 둔 세 선택지 ⑴ 잠금 테이블
⑵ 파일 잠금 ⑶ 겹쳐 쓰기 감수 중 ⑵다.

잠금에 필요한 성질은 **「프로세스가 죽으면 저절로 풀린다」**였다(`#894`가 잠금을 연결에
건 이유). `flock`은 커널이 **열린 파일 기술자**에 거는 잠금이라 `kill -9`에도 남지
않으며, DB 기능에 기대지 않으므로 CUBRID·SQLite 어느 쪽으로 붙어도 같게 동작한다.

**막는 범위는 같은 기계다.** `#894`가 실제로 겪은 것(IDE 실행과 터미널 실행이 겹침)이
전부 같은 기계이고 CI는 러너마다 스위트가 하나다. 다른 기계에서 같은 원격 DB를 치는
경우는 막지 못한다 — 그 경로까지 덮으려면 `#1250`의 SAVEPOINT 격리가 답이다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import TEST_DATABASE_URL, _upgrade_failure_message

_ROOT = Path(__file__).resolve().parents[1]

#: 자식 프로세스에서 같은 파일에 `flock`을 시도한다. 잡히면 0, 막히면 3.
#: `conftest`를 import하지 않는다 — 그러면 자식이 스스로 잠금을 잡으려 든다.
_PROBE = (
    "import fcntl, sys\n"
    "h = open(sys.argv[1], 'a')\n"
    "try:\n"
    "    fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "except OSError:\n"
    "    sys.exit(3)\n"
    "sys.exit(0)\n"
)

async def test_the_running_suite_holds_the_lock(migrated_db):
    """다른 프로세스는 잠금을 잡지 못한다 — 이 스위트가 쥐고 있다.

    같은 프로세스에서 다시 `flock`을 걸면 **성공해 버린다**(같은 fd 소유자라 재진입이
    허용된다). 그래서 **자식 프로세스**로 확인한다 — 이 검사가 보려는 것이 바로
    「남이 못 잡는가」이기 때문이다.
    """
    import conftest

    path = conftest._suite_lock_path()
    assert path.exists(), f"잠금 파일이 없다: {path}"

    probe = subprocess.run(
        [sys.executable, "-c", _PROBE, str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert probe.returncode == 3, (
        f"다른 프로세스가 잠금을 잡았다 — 이 스위트가 쥐고 있지 않다.\n{probe.stdout}{probe.stderr}"
    )


def test_the_lock_is_scoped_to_the_target_database(migrated_db):
    """잠금 파일이 **대상 DB 이름**으로 갈린다 (`#1250`).

    다른 DB를 쓰는 실행끼리는 겹쳐도 된다 — 하나의 파일로 잠그면 그것까지 막는다.
    """
    import conftest
    from db_target import database_name

    name = database_name(conftest.TEST_DATABASE_URL)

    assert name, "대상 DB 이름을 읽지 못했다"
    assert name in conftest._suite_lock_path().name, (
        f"잠금 파일이 DB 이름으로 갈리지 않는다: {conftest._suite_lock_path()}"
    )


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
