#!/usr/bin/env python3
"""DB 백업 · 복구 리허설 · 복구 (#827 ⑴ · 2026-09-11 결정 2-⑤ 「#827 백업과 연계」).

배포 호스트에서 돈다. **표준 라이브러리만 쓴다** — 프로덕션 이미지는 wheel만 설치해
``scripts/``가 없고(``README`` 「재적재 진입점」), 호스트에 ``uv``·가상환경이 있다고 가정할
수 없다. ``pg_dump``·``pg_restore``·``psql``은 **db 컨테이너 안의 것**을 부른다 — 서버와
같은 판이라 판 차이로 덤프가 거절될 일이 없고, 호스트에 클라이언트를 깔 필요가 없다.

## 명령

::

    python3 scripts/db_backup.py backup                  # 덤프 + 검증 + 기록 + 보존 개수 정리
    python3 scripts/db_backup.py rehearse <덤프>          # 새 DB에 복구해 대조한 뒤 지운다
    python3 scripts/db_backup.py restore <덤프> --confirm <DB 이름>   # 운영 DB를 덤프로 교체

환경변수

- ``COMPOSE`` — 기본 ``docker compose -f docker-compose.prod.yml``. 개발 스택에 쓰려면
  ``COMPOSE="docker compose"``
- ``BACKUP_DIR`` — 기본 ``backups`` (저장소 루트 기준, ``.gitignore``·``.dockerignore``)
- ``BACKUP_KEEP`` — 기본 14. 이보다 오래된 덤프는 ``backup``이 지운다

## 무엇을 검증하는가

**만들기만 하고 복구해 보지 않은 백업은 백업이 아니다**(``#788`` · ``#827``). 그래서
``backup``은 덤프가 ``pg_restore``로 읽히는지 확인한 뒤에만 파일을 확정하고, ``rehearse``는
실제로 새 DB에 복구해 **리비전 · 테이블 목록 · 테이블별 행 수 · 트리거 수**를 대조한다.
CI의 docker 잡이 이 둘을 매 실행 돌린다(``.github/workflows/ci.yml``).

## 되돌릴 수 없는 downgrade와의 연계

``backup``은 성공하면 ``audit_log``에 ``DB_BACKUP`` 행을 남긴다. 프로덕션의 되돌릴 수 없는
downgrade는 **24시간 안의 이 행이 없으면** ``ALLOW_IRREVERSIBLE_DOWNGRADE``로 명시해도
막힌다(``src/cii_platform/db/migration_guard.py`` · ``DB_SCHEMA §8.1.2``).

## 주기

**하루 한 번**을 기본으로 둔다 — 호스트 cron 한 줄이다(``README`` 「백업·복구」). 덤프는
**같은 호스트**에 쌓인다. 호스트 자체를 잃는 사고에는 쓸 수 없으므로, 호스트 밖으로
옮기는 것은 DB를 어디에 둘지(``#788``)와 함께 정한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: ``migration_guard.BACKUP_ACTION``과 같아야 한다 — ``tests/test_db_backup_script.py``가 대조한다.
BACKUP_ACTION = "DB_BACKUP"

DEFAULT_COMPOSE = "docker compose -f docker-compose.prod.yml"
DEFAULT_DIR = "backups"
DEFAULT_KEEP = 14

#: 리허설이 복구하는 DB 이름의 꼬리. 운영 DB 이름에 붙여 만들고, 끝나면 지운다.
REHEARSAL_SUFFIX = "_restore_check"

#: 컨테이너 안에서 운영 DB에 붙는 psql. 사용자·DB 이름은 **컨테이너의 환경변수**를 쓴다 —
#: 호스트 셸에 ``POSTGRES_*``가 없어도 돈다(compose가 ``.env``로 넣은 값이 컨테이너에 있다).
_PSQL = 'psql -v ON_ERROR_STOP=1 -X -At -U "$POSTGRES_USER"'

#: 사용자 테이블 행 수. ``alembic_version``도 포함한다 — 복구된 리비전과 함께 대조된다.
_COUNT_SQL = (
    "SELECT string_agg(format('%s=%s', t.relname, "
    "(xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I', t.relname), "
    "false, true, '')))[1]::text), ',' ORDER BY t.relname) "
    "FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = 'public' AND t.relkind = 'r'"
)
_TRIGGER_SQL = (
    "SELECT count(*) FROM pg_trigger g JOIN pg_class t ON t.oid = g.tgrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = 'public' AND NOT g.tgisinternal"
)
_REVISION_SQL = "SELECT version_num FROM alembic_version"


class BackupError(RuntimeError):
    """백업·복구가 확인에 실패했다. 메시지가 곧 운영자에게 보이는 사유다."""


# ─────────────────────────────────────────────────────────────────────────────
# 컨테이너 호출
# ─────────────────────────────────────────────────────────────────────────────

#: ``(argv, stdin 파일, stdout 파일) -> stdout 바이트``. 검사에서 갈아 끼운다.
#:
#: 덤프는 **파일로 흘린다** — 메모리에 올리면 DB 크기만큼 호스트 메모리를 쓴다.
#: stdout 파일을 주면 반환값은 빈 바이트다.
Runner = Callable[[Sequence[str], Path | None, Path | None], bytes]


def run_process(
    argv: Sequence[str], stdin_path: Path | None = None, stdout_path: Path | None = None
) -> bytes:
    with ExitStack() as stack:
        fin = stack.enter_context(stdin_path.open("rb")) if stdin_path else subprocess.DEVNULL
        fout = stack.enter_context(stdout_path.open("wb")) if stdout_path else subprocess.PIPE
        result = subprocess.run(
            list(argv), stdin=fin, stdout=fout, stderr=subprocess.PIPE, check=False
        )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise BackupError(f"명령 실패({result.returncode}): {shlex.join(argv)}\n{detail}")
    return result.stdout or b""


@dataclass
class Db:
    """db 컨테이너에 명령을 보낸다. ``exec -T`` — 표준 입출력을 바이너리로 흘린다."""

    compose: list[str]
    run: Runner = run_process

    def sh(
        self, script: str, stdin_path: Path | None = None, stdout_path: Path | None = None
    ) -> bytes:
        argv = [*self.compose, "exec", "-T", "db", "sh", "-c", script]
        return self.run(argv, stdin_path, stdout_path)

    def compose_cmd(self, *args: str) -> bytes:
        return self.run([*self.compose, *args], None, None)

    def query(self, sql: str, database: str | None = None) -> str:
        target = shlex.quote(database) if database else '"$POSTGRES_DB"'
        out = self.sh(f"{_PSQL} -d {target} -c {shlex.quote(sql)}")
        return out.decode("utf-8").strip()

    def live_name(self) -> str:
        return self.sh('printf %s "$POSTGRES_DB"').decode("utf-8").strip()


def parse_counts(raw: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for part in raw.split(","):
        if part:
            name, _, value = part.partition("=")
            counts[name] = int(value)
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# 백업
# ─────────────────────────────────────────────────────────────────────────────


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(dump: Path) -> Path:
    return dump.with_suffix(".json")


def backup(
    db: Db, directory: Path, keep: int, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> Path:
    """덤프를 뜨고, 읽히는지 확인하고, 매니페스트와 감사 기록을 남긴다. 덤프 경로를 돌려준다.

    **행 수는 덤프 직전에 센다.** 그 사이에 쓰기가 있으면 리허설의 행 수 대조가 어긋날 수
    있다 — 그때는 리허설이 어긋난 테이블을 말하고 실패하며, 다시 뜨면 된다.
    """
    if keep < 1:
        raise BackupError("BACKUP_KEEP은 1 이상이어야 합니다.")
    directory.mkdir(parents=True, exist_ok=True)
    database = db.live_name()
    revision = db.query(_REVISION_SQL)
    counts = parse_counts(db.query(_COUNT_SQL))
    triggers = int(db.query(_TRIGGER_SQL))
    if not counts:
        raise BackupError(f"{database}에 테이블이 없습니다 — 마이그레이션 전의 DB입니다.")

    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    dump = directory / f"{database}_{stamp}_r{revision}.dump"
    partial = dump.with_suffix(".dump.partial")
    db.sh('pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc', stdout_path=partial)

    # 읽히는지 확인한다 — 잘린 덤프는 여기서 걸린다. 테이블 데이터 항목이 테이블 수만큼 있어야 한다.
    listing = db.sh("pg_restore -l", stdin_path=partial).decode("utf-8", "replace")
    data_entries = sum(1 for line in listing.splitlines() if " TABLE DATA " in line)
    if data_entries < len(counts):
        partial.unlink(missing_ok=True)
        raise BackupError(
            f"덤프에 테이블 데이터가 {data_entries}개뿐입니다(테이블 {len(counts)}개) — "
            "덤프가 불완전합니다."
        )
    partial.replace(dump)

    manifest = {
        "database": database,
        "created_at": now().isoformat(),
        "alembic_revision": revision,
        "sha256": sha256_of(dump),
        "size_bytes": dump.stat().st_size,
        "table_counts": counts,
        "trigger_count": triggers,
    }
    manifest_path(dump).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 되돌릴 수 없는 downgrade의 해제 조건이다(migration_guard). 자격 증명·경로는 싣지 않는다.
    details = json.dumps(
        {"file": dump.name, "sha256": manifest["sha256"], "alembic_revision": revision}
    )
    db.query(
        "INSERT INTO audit_log (action, details_json) "
        f"VALUES ('{BACKUP_ACTION}', $j${details}$j$::jsonb)"
    )

    prune(directory, database, keep)
    return dump


def prune(directory: Path, database: str, keep: int) -> list[Path]:
    """같은 DB의 덤프를 **이름순(= 시각순)** 으로 최근 ``keep``개만 남긴다. 지운 덤프를 돌려준다."""
    dumps = sorted(directory.glob(f"{database}_*.dump"))
    removed = dumps[:-keep] if len(dumps) > keep else []
    for dump in removed:
        dump.unlink()
        manifest_path(dump).unlink(missing_ok=True)
    return removed


# ─────────────────────────────────────────────────────────────────────────────
# 복구
# ─────────────────────────────────────────────────────────────────────────────


def load_manifest(dump: Path) -> dict:
    """매니페스트를 읽고 덤프의 sha256을 대조한다. 어긋나면 복구하지 않는다."""
    path = manifest_path(dump)
    if not dump.is_file():
        raise BackupError(f"덤프가 없습니다: {dump}")
    if not path.is_file():
        raise BackupError(f"매니페스트가 없습니다: {path} — 이 스크립트로 뜬 덤프만 복구합니다.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    actual = sha256_of(dump)
    if actual != manifest.get("sha256"):
        raise BackupError(
            f"덤프가 매니페스트와 다릅니다(sha256 {actual[:12]}…) — 손상된 파일입니다."
        )
    return manifest


def _restore_into(db: Db, dump: Path, target: str) -> None:
    quoted = shlex.quote(target)
    db.query(f'DROP DATABASE IF EXISTS "{target}"', database="postgres")
    db.query(f'CREATE DATABASE "{target}"', database="postgres")
    db.sh(
        f'pg_restore -U "$POSTGRES_USER" -d {quoted} --no-owner --exit-on-error',
        stdin_path=dump,
    )


def verify_restored(db: Db, target: str, manifest: dict) -> list[str]:
    """복구된 DB를 매니페스트와 대조한다. 어긋난 항목 목록(비면 통과)."""
    problems: list[str] = []
    revision = db.query(_REVISION_SQL, database=target)
    if revision != manifest["alembic_revision"]:
        problems.append(f"리비전 {revision} ≠ {manifest['alembic_revision']}")
    counts = parse_counts(db.query(_COUNT_SQL, database=target))
    expected: dict[str, int] = manifest["table_counts"]
    missing = sorted(set(expected) - set(counts))
    if missing:
        problems.append(f"없는 테이블 {', '.join(missing)}")
    for name in sorted(set(expected) & set(counts)):
        if counts[name] != expected[name]:
            problems.append(f"{name} 행 수 {counts[name]} ≠ {expected[name]}")
    triggers = int(db.query(_TRIGGER_SQL, database=target))
    if triggers != manifest["trigger_count"]:
        problems.append(f"트리거 {triggers}개 ≠ {manifest['trigger_count']}개")
    return problems


def rehearse(db: Db, dump: Path, keep_db: bool = False) -> str:
    """새 DB에 복구해 대조한다. 통과하면 그 DB를 지우고 요약을 돌려준다."""
    manifest = load_manifest(dump)
    target = f"{manifest['database']}{REHEARSAL_SUFFIX}"
    _restore_into(db, dump, target)
    problems = verify_restored(db, target, manifest)
    if not keep_db:
        db.query(f'DROP DATABASE IF EXISTS "{target}"', database="postgres")
    if problems:
        raise BackupError(
            "복구 리허설 실패 — " + " · ".join(problems) + ". 덤프 직전·직후에 쓰기가 있었다면 "
            "행 수가 어긋날 수 있습니다. 다시 백업을 떠 리허설하십시오."
        )
    tables = len(manifest["table_counts"])
    rows = sum(manifest["table_counts"].values())
    return (
        f"복구 리허설 통과 — 리비전 {manifest['alembic_revision']} · 테이블 {tables}개 · "
        f"행 {rows}개 · 트리거 {manifest['trigger_count']}개가 일치합니다."
    )


def restore(
    db: Db, dump: Path, confirm: str, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> str:
    """운영 DB를 덤프로 **교체**한다. 기존 DB는 지우지 않고 이름을 바꿔 남긴다.

    순서 — 새 DB에 복구 → 대조 → 앱 중지 → 운영 DB 이름 변경 → 새 DB를 운영 이름으로 →
    앱 기동. 대조에 실패하면 **앱을 멈추기 전에** 끝난다.
    """
    manifest = load_manifest(dump)
    live = db.live_name()
    if confirm != live:
        raise BackupError(
            f"--confirm 값이 운영 DB 이름({live})과 다릅니다 — 교체는 이름을 그대로 적어야 합니다."
        )
    if manifest["database"] != live:
        raise BackupError(f"이 덤프는 {manifest['database']}의 것입니다(운영 DB {live}).")
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    staged = f"{live}_restore_{stamp}"
    kept = f"{live}_before_restore_{stamp}"
    _restore_into(db, dump, staged)
    problems = verify_restored(db, staged, manifest)
    if problems:
        db.query(f'DROP DATABASE IF EXISTS "{staged}"', database="postgres")
        raise BackupError("복구 대조 실패 — 운영 DB는 그대로입니다: " + " · ".join(problems))
    db.compose_cmd("stop", "app")
    try:
        db.query(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{live}' AND pid <> pg_backend_pid()",
            database="postgres",
        )
        db.query(f'ALTER DATABASE "{live}" RENAME TO "{kept}"', database="postgres")
        db.query(f'ALTER DATABASE "{staged}" RENAME TO "{live}"', database="postgres")
    finally:
        db.compose_cmd("start", "app")
    # nginx는 기동할 때 `app`의 주소를 한 번 풀어 둔다(`frontend/nginx.conf`의 `proxy_pass`).
    # 앱 컨테이너를 멈췄다 켜면 주소가 바뀔 수 있고, 그러면 화면이 502를 낸다 — 화면이 떠
    # 있을 때만 다시 띄워 주소를 새로 풀게 한다(개발 스택에는 화면 서비스가 없을 수 있다).
    running = db.compose_cmd("ps", "--services", "--status", "running").decode("utf-8").split()
    if "frontend" in running:
        db.compose_cmd("restart", "frontend")
    return (
        f"복구 완료 — {live}를 {dump.name}로 교체했습니다. 이전 DB는 {kept}로 남겼습니다. "
        f'확인이 끝나면 지우십시오: DROP DATABASE "{kept}"'
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None, runner: Runner = run_process) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="덤프 + 검증 + 감사 기록 + 보존 개수 정리")
    p_reh = sub.add_parser("rehearse", help="새 DB에 복구해 대조한 뒤 지운다")
    p_reh.add_argument("dump", type=Path)
    p_reh.add_argument("--keep-db", action="store_true", help="대조가 끝나도 복구 DB를 남긴다")
    p_res = sub.add_parser("restore", help="운영 DB를 덤프로 교체한다(이전 DB는 남긴다)")
    p_res.add_argument("dump", type=Path)
    p_res.add_argument("--confirm", required=True, help="운영 DB 이름을 그대로 적는다")
    args = parser.parse_args(argv)

    db = Db(shlex.split(os.environ.get("COMPOSE", DEFAULT_COMPOSE)), runner)
    try:
        if args.command == "backup":
            directory = Path(os.environ.get("BACKUP_DIR", DEFAULT_DIR))
            keep = int(os.environ.get("BACKUP_KEEP", DEFAULT_KEEP))
            dump = backup(db, directory, keep)
            print(f"백업 완료 — {dump} (매니페스트 {manifest_path(dump).name})")
        elif args.command == "rehearse":
            print(rehearse(db, args.dump, keep_db=args.keep_db))
        else:
            print(restore(db, args.dump, args.confirm))
    except BackupError as error:
        print(f"실패: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
