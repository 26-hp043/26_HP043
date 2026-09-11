"""백업 · 복구 리허설 · 복구 스크립트 (``scripts/db_backup.py`` · #827 ⑴).

컨테이너 호출을 **대역으로 바꿔** 판단만 본다 — 무엇을 확정하고, 무엇을 거절하고, 어떤
순서로 운영 DB를 건드리는가. 실제 ``pg_dump``·``pg_restore``로 도는지는 CI의 docker 잡이
프로덕션 스택에서 매 실행 확인한다(``.github/workflows/ci.yml`` 「백업 · 복구」 단계).

DB가 필요 없다.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cii_platform.db import migration_guard

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "db_backup.py"


def _load():
    spec = importlib.util.spec_from_file_location("db_backup_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["db_backup_script"] = module  # dataclass가 모듈을 찾는다
    spec.loader.exec_module(module)
    return module


bk = _load()

_COUNTS = "alembic_version=1,vessel=4,voyage=12"
_LISTING = "\n".join(
    [
        ";; Archive created",
        "3001; 0 0 TABLE DATA public alembic_version cii",
        "3002; 0 0 TABLE DATA public vessel cii",
        "3003; 0 0 TABLE DATA public voyage cii",
    ]
)


class FakeContainer:
    """db 컨테이너 대역. 부른 명령을 순서대로 남기고, 스크립트 내용으로 응답을 고른다."""

    def __init__(self, *, listing: str = _LISTING, restored_counts: str = _COUNTS):
        self.calls: list[list[str]] = []
        self.listing = listing
        self.restored_counts = restored_counts
        self.restored_revision = "038"
        self.restored_triggers = "9"
        self.running_services = "db\napp\n"

    def __call__(self, argv, stdin_path, stdout_path) -> bytes:
        argv = list(argv)
        self.calls.append(argv)
        if argv[-3:-1] != ["sh", "-c"]:
            if "ps" in argv:
                return self.running_services.encode()
            return b""  # compose stop / start / restart
        script = argv[-1]
        on_target = " -d cii_restore" in script
        if script.startswith("printf"):
            return b"cii"
        if script.startswith("pg_dump"):
            assert stdout_path is not None, "덤프는 파일로 흘려야 한다"
            stdout_path.write_bytes(b"PGDMP-fake-archive")
            return b""
        if script.startswith("pg_restore -l"):
            assert stdin_path is not None
            return self.listing.encode()
        if script.startswith("pg_restore"):
            assert stdin_path is not None
            return b""
        if "alembic_version" in script and "string_agg" not in script:
            return (self.restored_revision if on_target else "038").encode()
        if "string_agg" in script:
            return (self.restored_counts if on_target else _COUNTS).encode()
        if "pg_trigger" in script:
            return (self.restored_triggers if on_target else "9").encode()
        return b""

    def scripts(self) -> list[str]:
        return [c[-1] for c in self.calls if c[-3:-1] == ["sh", "-c"]]

    def compose_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[-3:-1] != ["sh", "-c"]]


_NOW = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)


def _db(fake: FakeContainer):
    return bk.Db(["docker", "compose", "-f", "docker-compose.prod.yml"], fake)


def _backup(tmp_path: Path, fake: FakeContainer | None = None, keep: int = 14) -> Path:
    return bk.backup(_db(fake or FakeContainer()), tmp_path, keep, now=lambda: _NOW)


# ─────────────────────────────────────────────────────────────────────────────
# 백업
# ─────────────────────────────────────────────────────────────────────────────


def test_backup_writes_dump_and_manifest(tmp_path: Path):
    dump = _backup(tmp_path)

    assert dump.name == "cii_20260912T030000Z_r038.dump"
    manifest = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    assert manifest["database"] == "cii"
    assert manifest["alembic_revision"] == "038"
    assert manifest["sha256"] == bk.sha256_of(dump)
    assert manifest["table_counts"] == {"alembic_version": 1, "vessel": 4, "voyage": 12}
    assert manifest["trigger_count"] == 9
    assert not list(tmp_path.glob("*.partial")), "확정 뒤에는 임시 파일이 남지 않는다"


def test_backup_leaves_the_record_the_downgrade_guard_looks_for(tmp_path: Path):
    """되돌릴 수 없는 downgrade의 해제 조건이다 — 이 행이 없으면 가드가 막는다."""
    fake = FakeContainer()
    dump = _backup(tmp_path, fake)

    inserts = [s for s in fake.scripts() if "INSERT INTO audit_log" in s]
    assert len(inserts) == 1
    assert f"'{migration_guard.BACKUP_ACTION}'" in inserts[0]
    assert dump.name in inserts[0]
    assert bk.sha256_of(dump) in inserts[0]


def test_script_and_guard_agree_on_the_action_name():
    assert bk.BACKUP_ACTION == migration_guard.BACKUP_ACTION


def test_incomplete_dump_is_not_kept_and_not_recorded(tmp_path: Path):
    """``pg_restore -l``로 읽어 테이블 데이터가 모자라면 덤프를 확정하지 않는다."""
    fake = FakeContainer(listing=";; Archive created\n3001; 0 0 TABLE DATA public vessel cii")

    with pytest.raises(bk.BackupError, match="불완전"):
        _backup(tmp_path, fake)

    assert not list(tmp_path.iterdir()), "덤프·임시 파일·매니페스트가 하나도 남지 않는다"
    assert not any("INSERT INTO audit_log" in s for s in fake.scripts())


def test_commands_run_inside_the_db_container_without_a_tty(tmp_path: Path):
    """``-T``가 없으면 바이너리 덤프가 TTY를 거쳐 깨진다."""
    fake = FakeContainer()
    _backup(tmp_path, fake)

    for call in fake.calls:
        assert call[:7] == [
            "docker",
            "compose",
            "-f",
            "docker-compose.prod.yml",
            "exec",
            "-T",
            "db",
        ]


def test_prune_keeps_the_newest_of_this_database_only(tmp_path: Path):
    for stamp in ("20260901T000000Z", "20260902T000000Z", "20260903T000000Z"):
        (tmp_path / f"cii_{stamp}_r038.dump").write_bytes(b"x")
        (tmp_path / f"cii_{stamp}_r038.json").write_text("{}")
    other = tmp_path / "other_20260801T000000Z_r038.dump"
    other.write_bytes(b"x")

    removed = bk.prune(tmp_path, "cii", keep=2)

    assert [p.name for p in removed] == ["cii_20260901T000000Z_r038.dump"]
    assert not (tmp_path / "cii_20260901T000000Z_r038.json").exists()
    assert (tmp_path / "cii_20260903T000000Z_r038.dump").exists()
    assert other.exists(), "다른 DB의 덤프는 건드리지 않는다"


def test_keep_must_be_positive(tmp_path: Path):
    with pytest.raises(bk.BackupError, match="1 이상"):
        _backup(tmp_path, keep=0)


# ─────────────────────────────────────────────────────────────────────────────
# 복구 리허설
# ─────────────────────────────────────────────────────────────────────────────


def test_rehearsal_restores_into_a_separate_database_and_drops_it(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer()

    summary = bk.rehearse(_db(fake), dump)

    assert "통과" in summary and "테이블 3개" in summary and "행 17개" in summary
    scripts = fake.scripts()
    assert any('CREATE DATABASE "cii_restore_check"' in s for s in scripts)
    assert any(s.startswith("pg_restore") and "cii_restore_check" in s for s in scripts)
    assert 'DROP DATABASE IF EXISTS "cii_restore_check"' in scripts[-1]
    assert not any('"cii"' in s and "DROP" in s for s in scripts), "운영 DB는 지우지 않는다"


def test_rehearsal_names_the_table_whose_rows_differ(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1,vessel=3,voyage=12")

    with pytest.raises(bk.BackupError, match="vessel 행 수 3 ≠ 4"):
        bk.rehearse(_db(fake), dump)

    assert 'DROP DATABASE IF EXISTS "cii_restore_check"' in fake.scripts()[-1]


def test_rehearsal_catches_a_missing_table_and_revision(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1,vessel=4")
    fake.restored_revision = "037"

    with pytest.raises(bk.BackupError) as info:
        bk.rehearse(_db(fake), dump)

    assert "없는 테이블 voyage" in str(info.value)
    assert "리비전 037 ≠ 038" in str(info.value)


def test_corrupted_dump_is_refused_before_touching_the_server(tmp_path: Path):
    dump = _backup(tmp_path)
    dump.write_bytes(b"PGDMP-tampered")
    fake = FakeContainer()

    with pytest.raises(bk.BackupError, match="손상"):
        bk.rehearse(_db(fake), dump)

    assert fake.calls == []


def test_dump_without_manifest_is_refused(tmp_path: Path):
    dump = tmp_path / "cii_x.dump"
    dump.write_bytes(b"x")

    with pytest.raises(bk.BackupError, match="매니페스트가 없습니다"):
        bk.rehearse(_db(FakeContainer()), dump)


# ─────────────────────────────────────────────────────────────────────────────
# 복구(교체)
# ─────────────────────────────────────────────────────────────────────────────


def test_restore_requires_the_live_name_verbatim(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer()

    with pytest.raises(bk.BackupError, match="--confirm"):
        bk.restore(_db(fake), dump, confirm="yes", now=lambda: _NOW)

    assert fake.compose_calls() == [], "앱을 멈추지 않는다"
    assert not any("CREATE DATABASE" in s for s in fake.scripts())


def test_restore_that_fails_verification_never_stops_the_app(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1,vessel=0,voyage=12")

    with pytest.raises(bk.BackupError, match="운영 DB는 그대로"):
        bk.restore(_db(fake), dump, confirm="cii", now=lambda: _NOW)

    assert fake.compose_calls() == []
    assert not any("RENAME" in s for s in fake.scripts())
    assert 'DROP DATABASE IF EXISTS "cii_restore_20260912T030000Z"' in fake.scripts()[-1]


def test_restore_keeps_the_previous_database_and_swaps_in_order(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer()

    message = bk.restore(_db(fake), dump, confirm="cii", now=lambda: _NOW)

    steps = []
    for call in fake.calls:
        if call[-3:-1] != ["sh", "-c"]:
            steps.append(" ".join(call[-2:]))
        elif "RENAME" in call[-1] or "pg_terminate_backend" in call[-1]:
            steps.append(call[-1])
    assert steps[0] == "stop app"
    assert "pg_terminate_backend" in steps[1]
    assert 'ALTER DATABASE "cii" RENAME TO "cii_before_restore_20260912T030000Z"' in steps[2]
    assert 'ALTER DATABASE "cii_restore_20260912T030000Z" RENAME TO "cii"' in steps[3]
    assert steps[4] == "start app"
    assert "restart frontend" not in steps, "화면 서비스가 없으면 건드리지 않는다"
    assert not any("DROP DATABASE" in s and "before_restore" in s for s in fake.scripts())
    assert "cii_before_restore_20260912T030000Z" in message


def test_restore_restarts_the_frontend_so_nginx_resolves_the_app_again(tmp_path: Path):
    """nginx는 기동 때 `app` 주소를 풀어 둔다 — 앱을 멈췄다 켜면 주소가 바뀔 수 있다."""
    dump = _backup(tmp_path)
    fake = FakeContainer()
    fake.running_services = "db\napp\nfrontend\n"

    bk.restore(_db(fake), dump, confirm="cii", now=lambda: _NOW)

    tail = [" ".join(c[-2:]) for c in fake.compose_calls() if "ps" not in c]
    assert tail[-2:] == ["start app", "restart frontend"]


def test_restore_refuses_a_dump_of_another_database(tmp_path: Path):
    dump = _backup(tmp_path)
    manifest = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    manifest["database"] = "other"
    bk.manifest_path(dump).write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(bk.BackupError, match="other의 것"):
        bk.restore(_db(FakeContainer()), dump, confirm="cii", now=lambda: _NOW)


# ─────────────────────────────────────────────────────────────────────────────
# CLI · 실행 환경
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_reports_failure_with_exit_code_1(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    fake = FakeContainer(listing="")

    assert bk.main(["backup"], runner=fake) == 1
    assert "실패:" in capsys.readouterr().err


def test_cli_uses_the_compose_command_from_the_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("COMPOSE", "docker compose -p demo")
    fake = FakeContainer()

    assert bk.main(["backup"], runner=fake) == 0
    assert fake.calls[0][:4] == ["docker", "compose", "-p", "demo"]


def test_script_uses_only_the_standard_library():
    """배포 호스트에는 가상환경이 없다 — 표준 라이브러리 밖을 import하면 거기서 돌지 않는다."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    outside = sorted(name for name in imported if name not in sys.stdlib_module_names)
    assert outside == [], outside
