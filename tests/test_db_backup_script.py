"""백업 · 복구 리허설 · 복구 스크립트 (``scripts/db_backup.py`` · #827 ⑴ · CUBRID #1058).

컨테이너 호출을 **대역으로 바꿔** 판단만 본다 — 무엇을 확정하고, 무엇을 거절하고, 어떤
순서로 운영 DB를 건드리는가. 실제 ``cubrid unloaddb``·``loaddb``로 도는지는 CI의 docker
잡이 프로덕션 스택에서 매 실행 확인한다(``.github/workflows/ci.yml`` 「백업 · 복구」 단계).

DB가 필요 없다.

## CUBRID로 옮기면서 이 파일에서 달라진 것

* 덤프가 **파일 하나가 아니라 tar 하나**다 — ``unloaddb``가 네 파일을 내므로 묶는다.
  그래서 대역이 **진짜 tar를 쓴다**: 스크립트가 ``tarfile``로 열어 ``%class`` 머리를
  세므로, 가짜 바이트를 주면 검증 경로가 통째로 건너뛰어진다.
* 완전성 검사가 ``pg_restore -l``의 ``TABLE DATA`` 줄에서 ``db_objects``의 ``%class``
  머리로 바뀌었다.
* 교체가 ``ALTER DATABASE … RENAME``에서 ``cubrid renamedb``로, ``pg_terminate_backend``
  가 ``cubrid server stop``으로 바뀌었다 — ``renamedb``는 서버가 멈춘 DB만 바꾼다.
* 대상 DB를 묻는 ``csql``에 **``-S``(standalone)** 가 붙는다 — 갓 만든 DB에는 서버가
  없어서 client-server 모드로는 조용히 빈 답이 온다.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
import tarfile
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

_TABLES = ("alembic_version", "vessel", "voyage")
_COUNTS = "alembic_version=1\nvessel=4\nvoyage=12"


def _objects_bytes(classes: tuple[str, ...]) -> bytes:
    """``unloaddb``의 objects 파일 모양 — 표마다 ``%class`` 머리 한 줄."""
    lines = [f"%id [dba].[{name}] {30 + i}" for i, name in enumerate(classes)]
    lines += [f"%class [dba].[{name}] ([id])" for name in classes]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_dump(path: Path, classes: tuple[str, ...]) -> None:
    """네 파일이 든 tar를 만든다 — 스크립트가 여는 것과 같은 모양이다."""
    with tarfile.open(path, "w") as archive:
        for member, payload in (
            (bk.SCHEMA_MEMBER, b"CREATE CLASS [dba].[vessel];\n"),
            (bk.INDEX_MEMBER, b"CREATE INDEX idx_x ON [dba].[vessel] ([id]);\n"),
            (bk.OBJECT_MEMBER, _objects_bytes(classes)),
            (bk.TRIGGER_MEMBER, b"CREATE TRIGGER [dba].[t] BEFORE DELETE ON [dba].[vessel];\n"),
        ):
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


class FakeContainer:
    """db 컨테이너 대역. 부른 명령을 순서대로 남기고, 스크립트 내용으로 응답을 고른다."""

    def __init__(self, *, dumped: tuple[str, ...] = _TABLES, restored_counts: str = _COUNTS):
        self.calls: list[list[str]] = []
        self.dumped = dumped
        self.restored_counts = restored_counts
        self.restored_revision = "049"
        self.restored_triggers = "146"
        self.running_services = "db\napp\n"
        #: ``databases.txt``의 vol-path. 실측 형태다 — ``cii`` 는 자기 이름의 폴더에 있다.
        self.volume_dir = "/home/cubrid/CUBRID/databases/cii"

    def __call__(self, argv, stdin_path, stdout_path) -> bytes:
        argv = list(argv)
        self.calls.append(argv)
        if argv[-3:-1] != ["sh", "-c"]:
            if "ps" in argv:
                return self.running_services.encode()
            return b""  # compose stop / start / restart
        script = argv[-1]
        # 운영 DB는 `"$CUBRID_DB"`로만 가리킨다 — 이름이 적혀 있으면 복구 대상이다.
        on_live = '"$CUBRID_DB"' in script
        if script.startswith("printf"):
            return b"cii"
        if "databases.txt" in script:
            return self.volume_dir.encode()
        if "cubrid unloaddb" in script:
            assert stdout_path is not None, "덤프는 파일로 흘려야 한다"
            assert "tar -cf -" in script, "네 파일을 tar 하나로 묶어야 한다"
            _write_dump(stdout_path, self.dumped)
            return b""
        if "tar -xf -" in script:
            assert stdin_path is not None, "덤프를 컨테이너로 흘려 넣어야 한다"
            return b""
        if "cubrid createdb" in script or "cubrid renamedb" in script:
            return b""
        if "cubrid server" in script or "cubrid deletedb" in script:
            return b""
        if "db_collation" in script:
            return b"en_US.iso88591"
        if "db_class" in script:
            return "\n".join(_TABLES).encode()
        if "CAST(count(*) AS VARCHAR)" in script:
            return (_COUNTS if on_live else self.restored_counts).encode()
        if "db_trigger" in script:
            return b"146" if on_live else self.restored_triggers.encode()
        if "alembic_version" in script:
            return b"049" if on_live else self.restored_revision.encode()
        return b""

    def scripts(self) -> list[str]:
        return [c[-1] for c in self.calls if c[-3:-1] == ["sh", "-c"]]

    def compose_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[-3:-1] != ["sh", "-c"]]


_NOW = datetime(2026, 9, 16, 3, 0, tzinfo=UTC)


def _db(fake: FakeContainer):
    return bk.Db(["docker", "compose", "-f", "docker-compose.prod.yml"], fake)


def _backup(tmp_path: Path, fake: FakeContainer | None = None, keep: int = 14) -> Path:
    return bk.backup(_db(fake or FakeContainer()), tmp_path, keep, now=lambda: _NOW)


# ─────────────────────────────────────────────────────────────────────────────
# 백업
# ─────────────────────────────────────────────────────────────────────────────


def test_backup_writes_dump_and_manifest(tmp_path: Path):
    dump = _backup(tmp_path)

    assert dump.name == "cii_20260916T030000Z_r049.dump"
    manifest = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    assert manifest["database"] == "cii"
    assert manifest["alembic_revision"] == "049"
    assert manifest["sha256"] == bk.sha256_of(dump)
    assert manifest["table_counts"] == {"alembic_version": 1, "vessel": 4, "voyage": 12}
    assert manifest["trigger_count"] == 146
    assert not list(tmp_path.glob("*.partial")), "확정 뒤에는 임시 파일이 남지 않는다"


def test_manifest_says_the_dump_is_not_a_postgresql_archive(tmp_path: Path):
    """확장자가 ``.dump``인데 내용은 tar다 — 파일이 스스로 밝혀야 한다 (`#1058`)."""
    dump = _backup(tmp_path)

    manifest = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    assert manifest["format"] == bk.DUMP_FORMAT
    with tarfile.open(dump) as archive:
        assert set(archive.getnames()) == {
            bk.SCHEMA_MEMBER,
            bk.INDEX_MEMBER,
            bk.OBJECT_MEMBER,
            bk.TRIGGER_MEMBER,
        }


def test_backup_carries_the_triggers_that_are_the_constraints(tmp_path: Path):
    """트리거 수가 매니페스트에 실린다 — 이 배포에서 트리거는 **제약 그 자체**다.

    CUBRID가 CHECK를 강제하지 않아 `046`·`047`·`048`이 CHECK 60개와 부분 유니크를 전부
    트리거로 옮겼다(`DB_SCHEMA §7.4`). 트리거가 빠진 복구는 **제약이 없는 DB**이므로,
    수를 싣지 않으면 리허설이 그것을 보지 못한다.
    """
    fake = FakeContainer()
    dump = _backup(tmp_path, fake)

    assert json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))["trigger_count"] == 146
    unload = next(s for s in fake.scripts() if "cubrid unloaddb" in s)
    assert bk.TRIGGER_MEMBER in unload, "트리거 파일을 tar에 넣어야 한다"


def test_backup_leaves_the_record_the_downgrade_guard_looks_for(tmp_path: Path):
    """되돌릴 수 없는 downgrade의 해제 조건이다 — 이 행이 없으면 가드가 막는다."""
    fake = FakeContainer()
    dump = _backup(tmp_path, fake)

    inserts = [s for s in fake.scripts() if "INSERT INTO audit_log" in s]
    assert len(inserts) == 1
    assert f"'{migration_guard.BACKUP_ACTION}'" in inserts[0]
    assert dump.name in inserts[0]
    assert bk.sha256_of(dump) in inserts[0]
    # `action`은 CUBRID 예약어이고 `id`는 기본값이 없다 — 둘 중 하나만 빠져도 감사
    # 기록이 조용히 안 남고, 그러면 downgrade 가드가 영영 풀리지 않는다.
    assert '"action"' in inserts[0]
    assert "audit_log (id, " in inserts[0]


def test_script_and_guard_agree_on_the_action_name():
    assert bk.BACKUP_ACTION == migration_guard.BACKUP_ACTION


def test_incomplete_dump_is_not_kept_and_not_recorded(tmp_path: Path):
    """objects 파일의 ``%class`` 머리가 모자라면 덤프를 확정하지 않는다."""
    fake = FakeContainer(dumped=("alembic_version", "vessel"))  # voyage가 빠졌다

    with pytest.raises(bk.BackupError, match="voyage"):
        _backup(tmp_path, fake)

    assert not list(tmp_path.iterdir()), "덤프·임시 파일·매니페스트가 하나도 남지 않는다"
    assert not any("INSERT INTO audit_log" in s for s in fake.scripts())


def test_a_truncated_archive_is_caught_before_the_dump_is_confirmed(tmp_path: Path):
    """잘린 tar는 ``tarfile``이 여는 자리에서 걸린다 — 종전 ``pg_restore -l``의 자리다."""

    class Truncating(FakeContainer):
        def __call__(self, argv, stdin_path, stdout_path):
            script = list(argv)[-1]
            if list(argv)[-3:-1] == ["sh", "-c"] and "cubrid unloaddb" in script:
                self.calls.append(list(argv))
                assert stdout_path is not None
                stdout_path.write_bytes(b"not-a-tar-at-all")
                return b""
            return super().__call__(argv, stdin_path, stdout_path)

    fake = Truncating()
    with pytest.raises(bk.BackupError, match="tar로 읽지 못했습니다"):
        _backup(tmp_path, fake)

    assert not list(tmp_path.iterdir())


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


def test_every_csql_call_carries_the_password(tmp_path: Path):
    """배포 호스트는 ``ALTER USER dba PASSWORD``로 비밀번호를 건다 (`결정요청 §0-4`).

    ``-p``가 빠진 ``csql``은 거기서 ``errno=-171``로 선다 — 빈 값도 ``-p ""``로
    통과하므로 **항상 붙인다.**
    """
    fake = FakeContainer()
    _backup(tmp_path, fake)

    for script in fake.scripts():
        for client in ("csql ", "cubrid unloaddb ", "cubrid loaddb "):
            if client in script:
                assert '-p "$CUBRID_PASSWORD"' in script, script


def test_prune_keeps_the_newest_of_this_database_only(tmp_path: Path):
    for stamp in ("20260901T000000Z", "20260902T000000Z", "20260903T000000Z"):
        (tmp_path / f"cii_{stamp}_r049.dump").write_bytes(b"x")
        (tmp_path / f"cii_{stamp}_r049.json").write_text("{}")
    other = tmp_path / "other_20260801T000000Z_r049.dump"
    other.write_bytes(b"x")

    removed = bk.prune(tmp_path, "cii", keep=2)

    assert [p.name for p in removed] == ["cii_20260901T000000Z_r049.dump"]
    assert not (tmp_path / "cii_20260901T000000Z_r049.json").exists()
    assert (tmp_path / "cii_20260903T000000Z_r049.dump").exists()
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
    assert any("cubrid createdb" in s and "cii_chk" in s for s in scripts)
    assert any("cubrid loaddb" in s and "cii_chk" in s for s in scripts)
    assert "cubrid deletedb cii_chk" in scripts[-1]
    assert not any("cii_chk" not in s and "deletedb" in s for s in scripts), (
        "운영 DB는 지우지 않는다"
    )


def test_the_staged_database_lands_beside_the_live_one(tmp_path: Path):
    """``renamedb``는 볼륨을 **제자리에서** 이름만 바꾼다 (`#1058`).

    새 DB를 아무 데나 만들면 교체 뒤 **운영 DB의 볼륨이 ``cii_restore_<시각>`` 폴더에
    남는다** — 운영자가 3시에 그것을 찾지 못한다. 그래서 ``databases.txt``의 vol-path를
    읽어 같은 자리에 만든다.
    """
    dump = _backup(tmp_path)
    fake = FakeContainer()

    bk.rehearse(_db(fake), dump)

    assert any("databases.txt" in s for s in fake.scripts()), "vol-path를 읽어야 한다"
    createdb = next(s for s in fake.scripts() if "cubrid createdb" in s)
    assert "-F /home/cubrid/CUBRID/databases/cii " in createdb, createdb


def test_the_restored_database_gets_modest_volumes_and_shows_its_error(tmp_path: Path):
    """🔴 볼륨 크기를 기본값에 맡기지 않고, 실패하면 사유를 싣는다 (`#1058`).

    프로덕션 compose는 db 컨테이너에 ``memory: 512M``을 걸어 두었다. 기본
    ``db_volume_size``로 두 번째 DB를 만들면 CI에서 ``createdb``가 **exit 254**로 죽었고,
    출력을 ``>/dev/null``로 덮어 두었기 때문에 **이유가 어디에도 없었다.**
    """
    dump = _backup(tmp_path)
    fake = FakeContainer()

    bk.rehearse(_db(fake), dump)

    createdb = next(s for s in fake.scripts() if "cubrid createdb" in s)
    assert f"--db-volume-size={bk.RESTORE_DB_VOLUME_SIZE}" in createdb
    assert f"--log-volume-size={bk.RESTORE_LOG_VOLUME_SIZE}" in createdb
    # 실패 사유가 표준 오류로 나와야 한다 — 삼키면 다음 사람이 exit 코드만 본다.
    assert "_createdb.err" in createdb, createdb
    assert ">&2" in createdb, createdb
    # 두 명령의 출력이 파일로 가고, 실패할 때 그 파일을 표준 오류로 낸다.
    # (`2>/dev/null`은 오류 로그가 **없을 때**를 삼키는 것이라 여기서 세지 않는다.)
    for marker in ("/tmp/_createdb.out", "/tmp/_loaddb.out"):
        assert marker in createdb, f"{marker}가 없다 — 출력을 버리면 사유가 사라진다"


def test_the_fallback_path_is_expanded_by_the_shell_not_quoted_by_python(tmp_path: Path):
    """``databases.txt``에 줄이 없을 때의 폴백은 **셸 안**에 있어야 한다.

    파이썬이 ``"$CUBRID/databases"``를 들고 있다가 ``shlex.quote``로 감싸면
    ``'$CUBRID/databases'``가 되어 펼쳐지지 않는다 — ``$CUBRID``라는 이름의 디렉터리가
    생기고, 그 안에 만든 DB는 교체 뒤에 아무도 찾지 못한다.
    """
    assert 'printf %s "${d:-$CUBRID/databases}"' in bk._VOLUME_DIR_SH


def test_an_unreadable_volume_dir_stops_instead_of_guessing(tmp_path: Path):
    """빈 답을 기본값으로 때우면 ``createdb -F ''``가 된다 — 멈추는 것이 맞다."""
    dump = _backup(tmp_path)
    fake = FakeContainer()
    fake.volume_dir = ""

    with pytest.raises(bk.BackupError, match="databases.txt"):
        bk.rehearse(_db(fake), dump)

    assert not any("cubrid createdb" in s for s in fake.scripts())


def test_rehearsal_creates_the_database_with_the_live_locale(tmp_path: Path):
    """``createdb``는 로케일을 요구한다 — **살아 있는 DB에서 읽는다**(코드에 박지 않는다)."""
    dump = _backup(tmp_path)
    fake = FakeContainer()

    bk.rehearse(_db(fake), dump)

    createdb = next(s for s in fake.scripts() if "cubrid createdb" in s)
    assert "en_US.iso88591" in createdb


def test_rehearsal_loads_data_before_triggers(tmp_path: Path):
    """네 파일을 **한 번에** 넘겨야 한다 — ``loaddb``가 데이터를 트리거보다 먼저 넣는다.

    따로 부르면 순서가 사람 손에 달리고, 트리거를 먼저 걸면 불변성 트리거
    (``trg_calcrun_no_delete``)가 적재를 막는다.
    """
    dump = _backup(tmp_path)
    fake = FakeContainer()

    bk.rehearse(_db(fake), dump)

    loaddb = next(s for s in fake.scripts() if "cubrid loaddb" in s)
    for flag, member in (
        ("-s", bk.SCHEMA_MEMBER),
        ("-i", bk.INDEX_MEMBER),
        ("--trigger-file", bk.TRIGGER_MEMBER),
        ("-d", bk.OBJECT_MEMBER),
    ):
        assert f"{flag} {member}" in loaddb


def test_queries_against_a_restored_database_are_standalone(tmp_path: Path):
    """서버가 없는 DB에 client-server로 붙으면 **조용히 빈 답**이 온다 — ``-S``가 필요하다.

    빈 답을 그대로 믿으면 리비전·행 수가 전부 어긋난 것으로 보이거나, 더 나쁘게는
    빈 표를 「없는 표」로 읽는다.
    """
    dump = _backup(tmp_path)
    fake = FakeContainer()

    bk.rehearse(_db(fake), dump)

    for script in fake.scripts():
        if "csql" in script and "cii_chk" in script:
            assert script.startswith("csql -S"), script
        elif "csql" in script and '"$CUBRID_DB"' in script:
            assert "-S" not in script, f"운영 DB에는 -S를 쓸 수 없다: {script}"


def test_rehearsal_names_the_table_whose_rows_differ(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1\nvessel=3\nvoyage=12")

    with pytest.raises(bk.BackupError, match="vessel 행 수 3 ≠ 4"):
        bk.rehearse(_db(fake), dump)

    assert "cubrid deletedb cii_chk" in fake.scripts()[-1]


def test_rehearsal_catches_a_missing_table_and_revision(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1\nvessel=4")
    fake.restored_revision = "048"

    with pytest.raises(bk.BackupError) as info:
        bk.rehearse(_db(fake), dump)

    assert "없는 테이블 voyage" in str(info.value)
    assert "리비전 048 ≠ 049" in str(info.value)


def test_rehearsal_catches_missing_triggers(tmp_path: Path):
    """제약이 트리거이므로 **트리거가 모자란 복구는 실패**여야 한다 (`DB_SCHEMA §7.4`)."""
    dump = _backup(tmp_path)
    fake = FakeContainer()
    fake.restored_triggers = "18"

    with pytest.raises(bk.BackupError, match="트리거 18개 ≠ 146개"):
        bk.rehearse(_db(fake), dump)


def test_corrupted_dump_is_refused_before_touching_the_server(tmp_path: Path):
    dump = _backup(tmp_path)
    dump.write_bytes(b"tampered")
    fake = FakeContainer()

    with pytest.raises(bk.BackupError, match="손상"):
        bk.rehearse(_db(fake), dump)

    assert fake.calls == []


def test_a_postgresql_era_dump_is_refused(tmp_path: Path):
    """PostgreSQL 시절 덤프에는 ``format``이 없다 — ``loaddb``에 넘기면 안 된다."""
    dump = _backup(tmp_path)
    manifest = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    del manifest["format"]
    bk.manifest_path(dump).write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(bk.BackupError, match="덤프 형식"):
        bk.rehearse(_db(FakeContainer()), dump)


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
    assert not any("cubrid createdb" in s for s in fake.scripts())


def test_restore_that_fails_verification_never_stops_the_app(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer(restored_counts="alembic_version=1\nvessel=0\nvoyage=12")

    with pytest.raises(bk.BackupError, match="운영 DB는 그대로"):
        bk.restore(_db(fake), dump, confirm="cii", now=lambda: _NOW)

    assert fake.compose_calls() == []
    assert not any("renamedb" in s for s in fake.scripts())
    assert "cubrid deletedb cii_s0916030000" in fake.scripts()[-1]


def test_restore_keeps_the_previous_database_and_swaps_in_order(tmp_path: Path):
    dump = _backup(tmp_path)
    fake = FakeContainer()

    message = bk.restore(_db(fake), dump, confirm="cii", now=lambda: _NOW)

    steps = []
    for call in fake.calls:
        if call[-3:-1] != ["sh", "-c"]:
            steps.append(" ".join(call[-2:]))
        elif "renamedb" in call[-1] or "cubrid server" in call[-1]:
            steps.append(call[-1])
    # 앞쪽에는 staged DB를 준비하며 부른 `server stop`·`deletedb`가 있다 — 교체 자체는
    # `stop app`부터다. 거기서부터 잘라 **순서**를 본다.
    swap = steps[steps.index("stop app") :]
    assert swap[0] == "stop app"
    # `renamedb`는 서버가 멈춘 DB만 바꾼다 — 멈추는 것이 이름 변경보다 **먼저**다.
    assert "cubrid server stop cii" in swap[1]
    assert "cubrid server stop cii_s0916030000" in swap[2]
    assert "cubrid renamedb cii cii_b0916030000" in swap[3]
    assert "cubrid renamedb cii_s0916030000 cii" in swap[4]
    assert "cubrid server start cii" in swap[5]
    assert swap[6] == "start app"
    assert "restart frontend" not in steps, "화면 서비스가 없으면 건드리지 않는다"
    assert not any("deletedb" in s and "before_restore" in s for s in fake.scripts())
    assert "cii_b0916030000" in message
    assert "cubrid deletedb" in message, "이전 DB를 어떻게 지우는지 알려 준다"


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
    fake = FakeContainer(dumped=("vessel",))

    assert bk.main(["backup"], runner=fake) == 1
    assert "실패:" in capsys.readouterr().err


def test_cli_uses_the_compose_command_from_the_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("COMPOSE", "docker compose -p demo")
    fake = FakeContainer()

    assert bk.main(["backup"], runner=fake) == 0
    assert fake.calls[0][:4] == ["docker", "compose", "-p", "demo"]


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 DB 이름 길이 — CUBRID의 한도 (`#1058`)
# ─────────────────────────────────────────────────────────────────────────────


def test_derived_names_never_exceed_the_cubrid_limit():
    """CUBRID의 DB 이름은 **17자를 넘을 수 없다**(실측: 17 OK · 18 FAIL).

    종전 PostgreSQL 판의 ``cii_before_restore_<시각>``은 35자였다. 그대로 CUBRID에 내면
    ``createdb``가 그 자리에서 죽는다 — 교체가 **앱을 멈춘 뒤에** 죽는 것이 아니라
    staged 적재 단계에서 죽으므로 운영 DB는 무사하지만, 백업이 영영 복구되지 않는다.
    """
    stamp = _NOW.strftime(bk.DB_STAMP_FORMAT)
    assert len(stamp) == 10, stamp
    for live in ("cii", "cii_test", "a", "abcdefghijklmnopq"):
        for tag, with_stamp in (
            (bk.TAG_REHEARSAL, ""),
            (bk.TAG_STAGED, stamp),
            (bk.TAG_KEPT, stamp),
        ):
            name = bk.derived_name(live, tag, with_stamp)
            assert len(name) <= bk.MAX_DB_NAME, f"{name} ({len(name)}자)"
            assert name != live, "파생 이름이 운영 DB 이름과 같으면 교체가 자기를 지운다"


def test_derived_names_do_not_double_the_underscore():
    """앞머리를 자른 끝의 ``_``를 떼지 않으면 ``cii__b…``가 된다."""
    # 자리(17 − 꼬리표 2 − 시각 10 = 5)를 채우고 끝이 `_`인 경우.
    assert bk.derived_name("cii_", bk.TAG_KEPT, "0916030000") == "cii_b0916030000"
    # 끝이 `_`가 아니면 자른 그대로 쓴다 — 17자를 꽉 채운다.
    assert bk.derived_name("cii_test", bk.TAG_KEPT, "0916030000") == "cii_t_b0916030000"
    assert bk.derived_name("cii", bk.TAG_REHEARSAL) == "cii_chk"


def test_the_staged_and_kept_names_differ_within_the_same_second():
    """같은 시각에 만든 둘이 같으면 ``renamedb``가 자기 위에 쓴다."""
    stamp = _NOW.strftime(bk.DB_STAMP_FORMAT)
    assert bk.derived_name("cii", bk.TAG_STAGED, stamp) != bk.derived_name(
        "cii", bk.TAG_KEPT, stamp
    )


def test_a_tag_longer_than_the_limit_is_refused():
    with pytest.raises(bk.BackupError, match="꼬리표"):
        bk.derived_name("cii", "_" * 20)


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


def _executable_source(path: Path) -> str:
    """문서 문자열과 주석을 걷어낸 소스.

    머리말은 **무엇이 달라졌는지**를 적으려고 ``pg_dump``·``pg_restore``를 일부러
    인용한다. 그것까지 금지하면 기록을 지우게 되므로, 실제로 실행되는 줄만 본다.
    """
    lines: list[str] = []
    in_doc = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if in_doc:
            if line.endswith('"""') or line == '"""':
                in_doc = False
            continue
        if line.startswith('"""') and not (len(line) > 5 and line.endswith('"""')):
            in_doc = True
            continue
        if line.startswith('"""') and line.endswith('"""'):
            continue
        if line.startswith("#"):
            continue
        lines.append(raw.split("  #")[0])
    return "\n".join(lines)


def test_script_has_no_postgresql_leftovers():
    """PostgreSQL 전용 이름이 남아 있으면 배포 호스트에서 그 줄이 선다 (`#1058`)."""
    source = _executable_source(_SCRIPT)
    for leftover in (
        "pg_dump",
        "pg_restore",
        "pg_trigger",
        "pg_stat_activity",
        "pg_terminate_backend",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "query_to_xml",
        "DROP DATABASE",
        "ALTER DATABASE",
    ):
        assert leftover not in source, leftover
