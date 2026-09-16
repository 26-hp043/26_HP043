#!/usr/bin/env python3
"""DB 백업 · 복구 리허설 · 복구 (#827 ⑴ · CUBRID 전환 #1058).

배포 호스트에서 돈다. **표준 라이브러리만 쓴다** — 프로덕션 이미지는 wheel만 설치해
``scripts/``가 없고(``README`` 「재적재 진입점」), 호스트에 ``uv``·가상환경이 있다고 가정할
수 없다. ``cubrid``·``csql``은 **db 컨테이너 안의 것**을 부른다 — 서버와 같은 판이라 판
차이로 덤프가 거절될 일이 없고, 호스트에 클라이언트를 깔 필요가 없다.

## 🔴 CUBRID로 옮기면서 무엇이 달라졌나 (`#1058`)

종전 판은 ``pg_dump -Fc`` 한 줄이 **파일 하나**를 냈고 ``pg_restore``가 그것을 읽었다.
CUBRID에는 그런 단일 아카이브가 없다. ``cubrid unloaddb``가 **네 파일**을 낸다 —
실측이다::

    cd /tmp/ul && cubrid unloaddb --output-prefix db cii
      → db_schema  db_indexes  db_objects  db_trigger  db_unloaddb.log

그래서 네 파일을 **tar 하나로 묶어** 종전과 같은 「덤프 파일 하나 + 매니페스트 하나」
모양을 유지한다. 확장자는 ``.dump`` 그대로다 — ``README``·CI·``.gitignore``가 그 이름으로
적혀 있고, 매니페스트의 ``format``이 내용물을 밝힌다. 안을 보려면 ``tar -tf <덤프>``다.

**트리거가 덤프에 실리는가 — 실린다.** 착수 전에 이것부터 쟀다(`결정요청 §0-1`)::

    csql -t -N -u dba cii -c "SELECT count(*) FROM db_trigger"  → 14
    grep -c "CREATE TRIGGER" db_trigger                         → 14

트리거는 이 배포의 **제약 그 자체**다 — CUBRID가 CHECK를 강제하지 않아 `046`·`047`·`048`이
CHECK 60개와 부분 유니크를 전부 트리거로 옮겼다(`DB_SCHEMA §7.4`). 트리거가 빠진 복구는
**제약이 없는 DB**이므로, 매니페스트가 트리거 수를 싣고 리허설이 그것을 대조한다.

### ``loaddb``의 적재 순서가 중요하다

``loaddb``는 **schema → objects → index → trigger** 순으로 적재한다(실측)::

    Total       96 statements executed.        (schema)
    Total 131 object(s) inserted, 0 failed.    (objects)
    Total       28 statements executed.        (index)
    Total       15 statements executed.        (trigger)

데이터가 트리거보다 **먼저** 들어가므로 불변성 트리거(``trg_calcrun_no_delete`` ·
``trg_snapshot_immutable_update``)와 값 범위 트리거가 적재를 막지 않는다. 네 파일을 한
번에 넘기는 것이 그 순서를 보장하는 방법이다 — 따로 부르면 순서가 사람 손에 달린다.

### 서버가 뜨지 않은 DB는 ``csql -S``로 묻는다

``createdb``로 갓 만든 DB에는 서버가 없다. 그 DB에 ``csql``을 client-server 모드로 붙이면
**아무것도 출력하지 않고 조용히 끝난다** — 실측이다. ``-S``(standalone)를 붙여야 답한다.
반대로 **운영 DB에는 ``-S``를 쓸 수 없다**(서버가 이미 물고 있다). 그래서
:meth:`Db.query`가 대상에 따라 모드를 가른다.

### 교체는 ``renamedb``이고, 그 전에 서버를 멈춰야 한다

PostgreSQL의 ``ALTER DATABASE … RENAME TO``에 대응하는 것은 ``cubrid renamedb``다.
``pg_terminate_backend``에 대응하는 것은 ``cubrid server stop``이며, 이름을 바꾸기 전에
반드시 멈춰야 한다. 바꾼 뒤 다시 띄운다.

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

DB 이름·비밀번호는 **컨테이너의 환경변수**(``CUBRID_DB``·``CUBRID_PASSWORD``)를 쓴다 —
호스트 셸에 없어도 돈다.

## 무엇을 검증하는가

**만들기만 하고 복구해 보지 않은 백업은 백업이 아니다**(``#788`` · ``#827``). 그래서
``backup``은 덤프가 **tar로 읽히고 테이블마다 ``%class`` 머리가 있는지** 확인한 뒤에만
파일을 확정하고(종전 ``pg_restore -l``의 자리), ``rehearse``는 실제로 새 DB에 복구해
**리비전 · 테이블 목록 · 테이블별 행 수 · 트리거 수**를 대조한다. CI의 docker 잡이 이 둘을
매 실행 돌린다(``.github/workflows/ci.yml``).

아카이브 검사는 **호스트에서 ``tarfile``로** 한다 — 표준 라이브러리이고, 컨테이너를 한 번
덜 부르며, 잘린 tar는 그 자리에서 걸린다.

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
import tarfile
import uuid
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

#: 🔴 **CUBRID의 DB 이름은 17자를 넘을 수 없다.** 실측이다 — 16·17자는 서고 18자부터
#: 선다. 넘기면 ``createdb``가 그 자리에서 죽는다::
#:
#:     cubrid createdb … cii_restore_20260916T040540Z en_US.iso88591
#:     → *** FATAL ERROR *** LOG FATAL ERROR: logpb_initialize_log_names
#:       Length of prefix logname "cii_restore_20260916T040540Z" is too long;
#:       the length must be less than 17.
#:
#: PostgreSQL에는 이 한도가 없어 종전 판은 ``cii_before_restore_20260916T040540Z``(35자)를
#: 그대로 썼다. 그래서 아래 이름들은 **길이를 맞춰 짧게** 만든다.
MAX_DB_NAME = 17

#: DB 이름에 붙이는 시각 — ``MMDDHHMMSS``. 파일 이름의 ``%Y%m%dT%H%M%SZ``(16자)는 여기에
#: 들어가지 않는다. 연도를 뺀 이유는 길이이고, **초를 남긴 이유는 유일성**이다 —
#: 같은 초에 두 번 교체하지 않는 한 ``renamedb``가 이름 충돌로 서지 않는다.
DB_STAMP_FORMAT = "%m%d%H%M%S"

#: 꼬리표 — 리허설용 / 적재 중인 새 DB / 교체 전에 남기는 DB.
TAG_REHEARSAL = "_chk"
TAG_STAGED = "_s"
TAG_KEPT = "_b"

#: 덤프 안 파일 이름의 앞머리. ``--output-prefix``로 **DB 이름과 무관하게** 고정한다 —
#: 교체 도중 DB 이름이 바뀌어도 ``restore``가 같은 이름을 찾는다.
DUMP_PREFIX = "db"
SCHEMA_MEMBER = f"{DUMP_PREFIX}_schema"
INDEX_MEMBER = f"{DUMP_PREFIX}_indexes"
OBJECT_MEMBER = f"{DUMP_PREFIX}_objects"
TRIGGER_MEMBER = f"{DUMP_PREFIX}_trigger"

#: 매니페스트에 싣는 형식 표시. 확장자가 ``.dump``인데 내용은 tar이므로 **파일이 스스로
#: 밝히게** 한다 — 다음 사람이 ``pg_restore``를 들이대지 않도록.
DUMP_FORMAT = "cubrid-unloaddb-tar-v1"

#: 컨테이너 안에서 덤프를 펼치는 자리. 볼륨이 아니라 컨테이너 파일시스템이다 —
#: 한 번 쓰고 지우는 중간 산출물이라 남길 이유가 없다.
WORK_DIR = "/var/tmp/bluelog-backup"

#: 운영 DB의 볼륨이 어디 있는지는 ``databases.txt``가 안다 — 두 번째 칸이 vol-path다.
#: 실측: ``cii`` → ``/home/cubrid/CUBRID/databases/cii`` · ``cii_test`` →
#: ``/home/cubrid/CUBRID/databases``. **새 DB를 같은 자리에 만든다** — 교체 뒤 운영 DB의
#: 볼륨이 ``cii_restore_<시각>`` 같은 이름의 디렉터리에 남으면 운영자가 찾지 못한다
#: (``renamedb``는 볼륨을 **제자리에서** 이름만 바꾼다).
#:
#: ⚠️ 폴백까지 **셸 안에서** 푼다. ``"$CUBRID/databases"``를 파이썬이 들고 있다가
#: ``shlex.quote``로 감싸면 ``'$CUBRID/databases'``가 되어 **셸이 펼치지 않는다** —
#: ``$CUBRID``라는 이름의 디렉터리가 생긴다(검사가 이것을 잡았다).
_VOLUME_DIR_SH = (
    'd=$(awk -v n="$CUBRID_DB" \'$1==n {print $2}\' "$CUBRID/databases/databases.txt"); '
    'printf %s "${d:-$CUBRID/databases}"'
)

#: 복구본을 만들 때 쓰는 볼륨 크기.
#:
#: ⚠️ **기본값에 맡기지 않는다.** 프로덕션 compose는 db 컨테이너에 ``memory: 512M``을
#: 걸어 두었고, ``cubrid.conf``의 기본 ``db_volume_size``로 두 번째 DB를 만들면 CI에서
#: ``createdb``가 **exit 254**로 죽었다 — 출력을 ``>/dev/null``로 덮어 두었기 때문에
#: **사유가 어디에도 없었다.** 그래서 아래 :func:`_restore_into`가 CUBRID의 오류 로그를
#: 직접 싣는다.
#:
#: 복구본은 원본만큼 클 필요가 없다 — CUBRID는 공간이 모자라면 볼륨을 **자동 확장**한다.
RESTORE_DB_VOLUME_SIZE = "64M"
RESTORE_LOG_VOLUME_SIZE = "64M"

#: 조회용 — ``-t``(plain-output) ``-N``(skip-column-names)이 ``psql -At``과 같은 출력을 낸다.
#: ``-p``를 **빠뜨리면 안 된다** — 배포 호스트는 ``ALTER USER dba PASSWORD``로 비밀번호를
#: 걸고(`deploy.yml`), 그러면 비밀번호 없는 ``csql``은 ``errno=-171``로 선다.
#: 빈 값도 ``-p ""``로 통과한다(실측).
_CSQL = 'csql -t -N -u dba -p "$CUBRID_PASSWORD"'

#: unloaddb·loaddb도 같은 자격으로 붙는다.
_CRED = '-u dba -p "$CUBRID_PASSWORD"'

_REVISION_SQL = "SELECT version_num FROM alembic_version"

#: 사용자 테이블 목록. PostgreSQL의 ``pg_class ⋈ pg_namespace``가 여기서는 ``db_class``다.
#: ``alembic_version``도 포함한다 — 복구된 리비전과 함께 대조된다.
_TABLES_SQL = "SELECT class_name FROM db_class WHERE is_system_class = 'NO' ORDER BY class_name"

#: 트리거 수. PostgreSQL은 ``pg_trigger``에서 내부 트리거를 걸러야 했는데, CUBRID의
#: ``db_trigger``에는 **사용자 트리거만** 들어 있다.
_TRIGGER_SQL = "SELECT count(*) FROM db_trigger"

#: DB 로케일. ``createdb``가 요구하는 ``<language>.<charset>`` 형태를 **살아 있는 DB에서
#: 읽는다** — 코드에 박으면 언젠가 다른 판에서 조용히 어긋난다.
_LOCALE_SQL = (
    "SELECT r.lang || '.' || c.charset_name "
    "FROM db_root r, db_collation c WHERE c.coll_id = r.charset"
)


def derived_name(live: str, tag: str, stamp: str = "") -> str:
    """운영 DB 이름에서 파생 DB 이름을 만든다. **반드시 17자 이하**다.

    길면 앞머리를 자른다 — 자르는 쪽이 ``createdb``가 죽는 쪽보다 낫고, 무엇이 무엇에서
    왔는지는 꼬리표와 이 스크립트의 출력이 말한다. 잘린 끝의 ``_``는 떼어 ``cii__b…``
    같은 이름이 나오지 않게 한다.
    """
    room = MAX_DB_NAME - len(tag) - len(stamp)
    if room < 1:
        raise BackupError(f"꼬리표가 너무 깁니다: {tag}{stamp}")
    return f"{live[:room].rstrip('_')}{tag}{stamp}"


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
        result = subprocess.run(  # noqa: S603
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
        """SQL 한 줄을 보낸다.

        ``database``를 주면 **그 DB에 standalone(-S)으로** 붙는다 — 갓 만든 DB에는 서버가
        없고, 서버 없는 DB에 client-server로 붙으면 조용히 빈 답을 준다(실측).
        생략하면 운영 DB에 client-server로 붙는다 — 그쪽은 서버가 이미 물고 있어
        ``-S``를 쓸 수 없다.
        """
        if database is None:
            client, target = _CSQL, '"$CUBRID_DB"'
        else:
            # `-S`는 **`csql`의 옵션**이다 — 스크립트 앞에 두면 `sh -c "-S csql …"`가
            # 되어 셸이 `sh: -S: invalid option`으로 선다(한 번 그렇게 냈다).
            client, target = _CSQL.replace("csql ", "csql -S ", 1), shlex.quote(database)
        out = self.sh(f"{client} {target} -c {shlex.quote(sql)}")
        return out.decode("utf-8").strip()

    def live_name(self) -> str:
        return self.sh('printf %s "$CUBRID_DB"').decode("utf-8").strip()

    def volume_dir(self) -> str:
        """운영 DB의 볼륨 디렉터리 — 셸이 **펼친 절대 경로**를 돌려준다.

        비어 오면 예외다. 기본값으로 때우면 ``createdb -F ''``가 되어 어디에 만들지
        모르는 상태로 이어진다 — 그 자리는 조용히 넘어갈 자리가 아니다.
        """
        found = self.sh(_VOLUME_DIR_SH).decode("utf-8").strip()
        if not found:
            raise BackupError(
                "DB 볼륨 디렉터리를 읽지 못했습니다 — 컨테이너의 "
                "$CUBRID/databases/databases.txt를 확인하십시오."
            )
        return found.splitlines()[0].strip()

    def tables(self, database: str | None = None) -> list[str]:
        raw = self.query(_TABLES_SQL, database)
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def counts(self, database: str | None = None) -> dict[str, int]:
        """테이블별 행 수. 표 목록을 먼저 받고 ``UNION ALL`` 한 문장으로 센다.

        CUBRID에는 PostgreSQL의 ``query_to_xml``이 없어 한 문장으로는 못 센다. 표마다
        따로 묻지 않는 이유는 왕복 횟수다 — 25표면 25번이고, 그 사이 쓰기가 끼면 수치가
        서로 다른 시점의 것이 된다.
        """
        names = self.tables(database)
        if not names:
            return {}
        parts = [
            f"SELECT '{name}' || '=' || CAST(count(*) AS VARCHAR) FROM {name}" for name in names
        ]
        return parse_counts(self.query(" UNION ALL ".join(parts), database))

    def trigger_count(self, database: str | None = None) -> int:
        return int(self.query(_TRIGGER_SQL, database) or 0)


def parse_counts(raw: str) -> dict[str, int]:
    """``name=n`` 줄(또는 쉼표로 이은 것)을 표로 읽는다."""
    counts: dict[str, int] = {}
    for line in raw.replace(",", "\n").splitlines():
        part = line.strip()
        if part:
            name, _, value = part.partition("=")
            counts[name.strip()] = int(value)
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# 덤프 아카이브
# ─────────────────────────────────────────────────────────────────────────────


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(dump: Path) -> Path:
    return dump.with_suffix(".json")


def dumped_classes(dump: Path) -> set[str]:
    """덤프의 objects 파일에 ``%class`` 머리가 있는 테이블 이름.

    종전 ``pg_restore -l``의 ``TABLE DATA`` 줄에 대응한다 — **빈 표에도 머리는 있다**
    (실측: 표 25개 → ``%class`` 25개, 그중 빈 표 5개). tar를 여는 것 자체가 잘린
    아카이브를 걸러 준다.
    """
    try:
        with tarfile.open(dump, "r:") as archive:
            member = archive.extractfile(OBJECT_MEMBER)
            if member is None:
                raise BackupError(f"덤프에 {OBJECT_MEMBER}가 없습니다 — 덤프가 불완전합니다.")
            names: set[str] = set()
            for raw in member:
                if not raw.startswith(b"%class"):
                    continue
                text = raw.decode("utf-8", "replace")
                # `%class [dba].[vessel] ([id] …)` — 마지막 대괄호 짝이 표 이름이다.
                head = text.split("(", 1)[0]
                pieces = [p for p in head.split("[") if "]" in p]
                if pieces:
                    names.add(pieces[-1].split("]")[0])
            return names
    except tarfile.TarError as error:
        raise BackupError(f"덤프를 tar로 읽지 못했습니다: {error}") from error


# ─────────────────────────────────────────────────────────────────────────────
# 백업
# ─────────────────────────────────────────────────────────────────────────────


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
    counts = db.counts()
    triggers = db.trigger_count()
    if not counts:
        raise BackupError(f"{database}에 테이블이 없습니다 — 마이그레이션 전의 DB입니다.")

    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    dump = directory / f"{database}_{stamp}_r{revision}.dump"
    partial = dump.with_suffix(".dump.partial")
    # 덤프와 tar 묶기를 **한 셸에서** 한다 — 컨테이너 안에 중간 파일을 남기지 않는다.
    # `unloaddb`는 살아 있는 DB에서 돈다(서버를 멈추지 않는다 · 실측).
    # 로그 파일(`db_unloaddb.log`)은 넣지 않는다 — 복구에 쓰이지 않고 경로가 찍힌다.
    db.sh(
        f"set -e; rm -rf {WORK_DIR}; mkdir -p {WORK_DIR}; cd {WORK_DIR}; "
        f'cubrid unloaddb {_CRED} --output-prefix {DUMP_PREFIX} "$CUBRID_DB" >/dev/null; '
        f"tar -cf - {SCHEMA_MEMBER} {INDEX_MEMBER} {OBJECT_MEMBER} {TRIGGER_MEMBER}; "
        f"rm -rf {WORK_DIR}",
        stdout_path=partial,
    )

    # 읽히는지 확인한다 — 잘린 덤프는 여기서 걸린다. 테이블마다 `%class` 머리가 있어야 한다.
    #
    # **실패하면 임시 파일을 지운다.** 남기면 다음 실행의 `prune`이 세는 대상이 되고,
    # 무엇보다 「덤프가 있다」로 보인다 — 확인에 실패한 덤프는 덤프가 아니다.
    try:
        dumped = dumped_classes(partial)
        missing = sorted(set(counts) - dumped)
        if missing:
            raise BackupError(
                f"덤프에 {', '.join(missing)}의 데이터 머리가 없습니다"
                f"(테이블 {len(counts)}개 중 {len(dumped)}개) — 덤프가 불완전합니다."
            )
    except BackupError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(dump)

    manifest = {
        "database": database,
        "format": DUMP_FORMAT,
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
    # `audit_log.id`는 CHAR(32)이고 기본값이 없다. `action`은 CUBRID 예약어라 인용한다.
    # dollar-quote는 CUBRID에 없으므로 작은따옴표를 SQL 표준대로 겹쳐 막는다
    # (`purge_expired.py`와 같은 자리).
    escaped = details.replace("'", "''")
    db.query(
        'INSERT INTO audit_log (id, "action", details_json) '
        f"VALUES ('{uuid.uuid4().hex}', '{BACKUP_ACTION}', '{escaped}')"
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
    if manifest.get("format") != DUMP_FORMAT:
        raise BackupError(
            f"덤프 형식이 {manifest.get('format')!r}입니다 — 이 스크립트는 "
            f"{DUMP_FORMAT!r}만 복구합니다(PostgreSQL 시절 덤프는 복구할 수 없습니다)."
        )
    return manifest


def _drop_database(db: Db, name: str) -> None:
    """DB를 지운다. **없어도 실패하지 않는다** — ``DROP DATABASE IF EXISTS``의 자리다.

    서버가 떠 있으면 ``deletedb``가 거부하므로 먼저 멈춘다. 둘 다 없는 상태가 정상일 수
    있어 실패를 삼킨다 — 그래서 ``|| true``다.
    """
    quoted = shlex.quote(name)
    db.sh(
        f"cubrid server stop {quoted} >/dev/null 2>&1 || true; "
        f"cubrid deletedb {quoted} >/dev/null 2>&1 || true"
    )


def _restore_into(db: Db, dump: Path, target: str, locale: str, volume_dir: str) -> None:
    """덤프를 컨테이너로 흘려 넣고 새 DB를 만들어 적재한다.

    네 파일을 **한 번에** 넘긴다 — ``loaddb``가 schema → objects → index → trigger 순으로
    적재하므로 데이터가 트리거보다 먼저 들어간다. 따로 부르면 그 순서가 사람 손에 달리고,
    트리거를 먼저 걸면 불변성 트리거가 적재를 막는다.
    """
    quoted = shlex.quote(target)
    _drop_database(db, target)
    db.sh(
        f"set -e; rm -rf {WORK_DIR}; mkdir -p {WORK_DIR}; tar -xf - -C {WORK_DIR}",
        stdin_path=dump,
    )
    where = shlex.quote(volume_dir)
    sizes = f"--db-volume-size={RESTORE_DB_VOLUME_SIZE} --log-volume-size={RESTORE_LOG_VOLUME_SIZE}"
    # 출력을 버리지 않는다 — **실패하면 사유를 싣는다.** `>/dev/null`로 덮었을 때 CI에서
    # `exit 254`만 남고 이유가 어디에도 없었다. `createdb`는 제 오류를
    # `$CUBRID/log/<db>_createdb.err`에도 적으므로 그것까지 함께 낸다.
    err_log = f"$CUBRID/log/{quoted}_createdb.err"
    db.sh(
        f"set -e; mkdir -p {where}; cd {WORK_DIR}; "
        f"cubrid createdb {sizes} -F {where} {quoted} {shlex.quote(locale)} "
        f'>/tmp/_createdb.out 2>&1 || {{ echo "--- createdb ---" >&2; '
        f"cat /tmp/_createdb.out >&2; cat {err_log} >&2 2>/dev/null; exit 1; }}; "
        f"cubrid loaddb {_CRED} -s {SCHEMA_MEMBER} -i {INDEX_MEMBER} "
        f"--trigger-file {TRIGGER_MEMBER} -d {OBJECT_MEMBER} {quoted} "
        f'>/tmp/_loaddb.out 2>&1 || {{ echo "--- loaddb ---" >&2; '
        f"cat /tmp/_loaddb.out >&2; exit 1; }}; "
        f"rm -rf {WORK_DIR}"
    )


def verify_restored(db: Db, target: str, manifest: dict) -> list[str]:
    """복구된 DB를 매니페스트와 대조한다. 어긋난 항목 목록(비면 통과)."""
    problems: list[str] = []
    revision = db.query(_REVISION_SQL, database=target)
    if revision != manifest["alembic_revision"]:
        problems.append(f"리비전 {revision} ≠ {manifest['alembic_revision']}")
    counts = db.counts(database=target)
    expected: dict[str, int] = manifest["table_counts"]
    missing = sorted(set(expected) - set(counts))
    if missing:
        problems.append(f"없는 테이블 {', '.join(missing)}")
    for name in sorted(set(expected) & set(counts)):
        if counts[name] != expected[name]:
            problems.append(f"{name} 행 수 {counts[name]} ≠ {expected[name]}")
    triggers = db.trigger_count(database=target)
    if triggers != manifest["trigger_count"]:
        problems.append(f"트리거 {triggers}개 ≠ {manifest['trigger_count']}개")
    return problems


def rehearse(db: Db, dump: Path, keep_db: bool = False) -> str:
    """새 DB에 복구해 대조한다. 통과하면 그 DB를 지우고 요약을 돌려준다."""
    manifest = load_manifest(dump)
    target = derived_name(manifest["database"], TAG_REHEARSAL)
    _restore_into(db, dump, target, db.query(_LOCALE_SQL), db.volume_dir())
    problems = verify_restored(db, target, manifest)
    if not keep_db:
        _drop_database(db, target)
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

    순서 — 새 DB에 복구 → 대조 → 앱 중지 → 운영 서버 중지 → 운영 DB 이름 변경 →
    새 DB를 운영 이름으로 → 운영 서버 기동 → 앱 기동. 대조에 실패하면 **앱을 멈추기
    전에** 끝난다.

    ``renamedb``는 **서버가 멈춘 DB만** 바꿀 수 있다. 그래서 ``pg_terminate_backend``의
    자리에 ``cubrid server stop``이 들어간다.
    """
    manifest = load_manifest(dump)
    live = db.live_name()
    if confirm != live:
        raise BackupError(
            f"--confirm 값이 운영 DB 이름({live})과 다릅니다 — 교체는 이름을 그대로 적어야 합니다."
        )
    if manifest["database"] != live:
        raise BackupError(f"이 덤프는 {manifest['database']}의 것입니다(운영 DB {live}).")
    locale = db.query(_LOCALE_SQL)
    stamp = now().strftime(DB_STAMP_FORMAT)
    staged = derived_name(live, TAG_STAGED, stamp)
    kept = derived_name(live, TAG_KEPT, stamp)
    _restore_into(db, dump, staged, locale, db.volume_dir())
    problems = verify_restored(db, staged, manifest)
    if problems:
        _drop_database(db, staged)
        raise BackupError("복구 대조 실패 — 운영 DB는 그대로입니다: " + " · ".join(problems))
    db.compose_cmd("stop", "app")
    try:
        # 갓 적재한 staged는 서버가 떠 있지 않지만, 확실히 멈춰 둔다 — 떠 있으면
        # `renamedb`가 거부하고 그 자리에서 교체가 반쯤 끝난 상태가 된다.
        db.sh(f"cubrid server stop {shlex.quote(live)} >/dev/null 2>&1 || true")
        db.sh(f"cubrid server stop {shlex.quote(staged)} >/dev/null 2>&1 || true")
        db.sh(f"set -e; cubrid renamedb {shlex.quote(live)} {shlex.quote(kept)}")
        db.sh(f"set -e; cubrid renamedb {shlex.quote(staged)} {shlex.quote(live)}")
        db.sh(f"set -e; cubrid server start {shlex.quote(live)}")
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
        f"확인이 끝나면 지우십시오: cubrid deletedb {kept}"
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
