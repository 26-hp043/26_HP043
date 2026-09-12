#!/usr/bin/env python3
"""만료 행 정리 — 세션 · 토큰 · 대화 (#827 ⑶ · #120 채팅 보존).

``user_session``·``user_token``·``chat_session``은 **단조 증가한다.** 만료된 행을
지우는 작업이 어디에도 없었다(`#827` 실측). 쌓이기만 하는 표는 느려지는 것보다
**남아 있으면 안 되는 것이 남는다**는 쪽이 문제다 — 만료된 세션 토큰 해시는
쓸모가 없고, 90일 지난 대화는 `PRD §16.3`이 지우라고 정한다.

``db_backup.py``와 같은 판이다 — **표준 라이브러리만** 쓰고, ``psql``은 db 컨테이너
안의 것을 부른다. 프로덕션 이미지는 wheel만 설치해 ``scripts/``가 없고, 호스트에
``uv``·가상환경이 있다고 가정할 수 없다.

## 명령

::

    python3 scripts/purge_expired.py                  # 지운다
    python3 scripts/purge_expired.py --dry-run        # 셀 뿐, 지우지 않는다
    python3 scripts/purge_expired.py --grace-days 30  # 세션·토큰 유예를 늘린다

환경변수

- ``COMPOSE`` — 기본 ``docker compose -f docker-compose.prod.yml``. 개발 스택에는
  ``COMPOSE="docker compose"``

## ⚠️ 무엇을 지우고 무엇을 안 지우나

**만료가 이미 지난 행만** 지운다. 「오래된 것」이 아니라 **「기한이 끝난 것」**이
기준이다 — 살아 있는 세션을 끊으면 사용자가 작업 중에 튕긴다.

===================  ================================================
 ``user_session``     ``expires_at`` 경과 **또는** ``revoked_at`` 있음
 ``user_token``       ``expires_at`` 경과 **또는** ``used_at`` 있음
 ``chat_session``     ``expires_at`` 경과 (생성 + 90일 · `PRD §16.3`)
===================  ================================================

**지우지 않는 것** — ``audit_log``·``calculation_run``. 전자는 보존 대상이고
(`DB_SCHEMA §7.1`) 후자는 immutable이다(`§7.3`). 로그인 이력을 알고 싶으면
``audit_log``의 ``LOGIN_SUCCESS``를 본다 — **세션 행은 이력이 아니라 상태**다.

## 유예 기간을 코드에 박지 않는다

세션·토큰의 보존 기간은 **정본에 없다.** 채팅은 `PRD §16.3`이 90일을 정해
``expires_at``에 이미 들어가 있지만, 세션·토큰은 그런 규정이 없다.

없는 정책을 여기서 만들지 않는다 — :data:`DEFAULT_GRACE_DAYS`를 보수적으로 두고
``--grace-days``로 받는다. 정책이 정해지면 그때 정본에 적고 기본값을 맞춘다.

## 대화를 지우면 메시지도 함께 사라진다

``chat_message``는 FK ``ON DELETE CASCADE``다(`041`). **두 번 지우지 않는다** —
세션만 지우고 메시지가 남으면 고아 행이 쌓이고, 그것이 곧 「지웠다고 했는데 남아
있는」 상태다.

## 주기

**하루 한 번**이면 충분하다 — 호스트 cron 한 줄이다. 만료 행은 그 사이 쌓여도
동작에 영향을 주지 않는다(조회가 ``expires_at``을 본다). 백업(``db_backup.py``)
**뒤에** 두면, 지운 것이 그날 덤프에는 남아 있어 잘못 지웠을 때 되돌릴 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: ``db_backup.py``와 같은 기본값.
DEFAULT_COMPOSE = "docker compose -f docker-compose.prod.yml"

_PSQL = 'psql -v ON_ERROR_STOP=1 -X -At -U "$POSTGRES_USER"'

#: 만료 **뒤** 며칠을 더 두는가.
#:
#: ⚠️ 이 값은 **정본에 근거가 없다.** 세션·토큰 보존 기간을 정한 문서가 없어
#: 보수적으로 둔 것이다(위 머리말). 정책이 정해지면 정본에 적고 여기를 맞춘다.
#:
#: 0이 아닌 이유 — 만료 직후의 행은 **장애 조사에 쓰인다.** 「어제 로그인이 안 됐다」는
#: 신고를 받았을 때 그 세션 행이 이미 없으면 확인할 것이 줄어든다.
DEFAULT_GRACE_DAYS = 7

#: 감사 로그 액션. ``db_backup.py``의 ``DB_BACKUP``과 같은 자리다 —
#: **스크립트가 한 일도 기록에 남는다.**
PURGE_ACTION = "EXPIRED_PURGE"

#: 세션·토큰은 유예를 적용한다. 채팅은 ``expires_at``이 이미 정본의 90일이라
#: 유예를 더하지 않는다 — 더하면 「90일 보존」이 사실과 달라진다.
_SQL = {
    "user_session": (
        "DELETE FROM user_session WHERE "
        "expires_at < now() - make_interval(days => {grace}) "
        "OR (revoked_at IS NOT NULL AND revoked_at < now() - make_interval(days => {grace}))"
    ),
    "user_token": (
        "DELETE FROM user_token WHERE "
        "expires_at < now() - make_interval(days => {grace}) "
        "OR (used_at IS NOT NULL AND used_at < now() - make_interval(days => {grace}))"
    ),
    "chat_session": "DELETE FROM chat_session WHERE expires_at < now()",
}

#: 세는 문장 — ``DELETE``를 ``SELECT count(*)``로 바꾼 것. 같은 조건을 두 번 적지
#: 않으려고 문자열을 갈아 끼운다. 조건이 갈리면 ``--dry-run``이 거짓말을 한다.
_COUNT_PREFIX = {
    "user_session": "SELECT count(*) FROM user_session WHERE ",
    "user_token": "SELECT count(*) FROM user_token WHERE ",
    "chat_session": "SELECT count(*) FROM chat_session WHERE ",
}


class QueryError(RuntimeError):
    """한 문장이 실패했다. **작업 전체를 세우지 않는다** — 아래 :func:`purge` 참조."""


def run_process(argv: list[str]) -> bytes:
    result = subprocess.run(argv, capture_output=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise QueryError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


@dataclass
class Db:
    """db 컨테이너에 명령을 보낸다 (``db_backup.py``와 같은 방식)."""

    compose: list[str]
    run: object = field(default=run_process)

    def query(self, sql: str) -> str:
        argv = [
            *self.compose,
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            f'{_PSQL} -d "$POSTGRES_DB" -c {shlex.quote(sql)}',
        ]
        return self.run(argv).decode("utf-8").strip()  # type: ignore[operator]


def count_sql(table: str, grace_days: int) -> str:
    """``--dry-run``이 쓰는 세는 문장. ``DELETE``와 **같은 조건**이어야 한다."""
    delete = _SQL[table].format(grace=grace_days)
    _, _, condition = delete.partition(" WHERE ")
    return _COUNT_PREFIX[table] + condition


def delete_sql(table: str, grace_days: int) -> str:
    return _SQL[table].format(grace=grace_days)


def purge(db: Db, *, grace_days: int, dry_run: bool) -> tuple[dict[str, int], dict[str, str]]:
    """표별로 지운(또는 지울) 행 수와, 실패한 표의 사유를 돌려준다.

    ⚠️ **표 하나가 실패해도 나머지는 계속한다.** 한 표의 잠금이나 부재 때문에
    나머지가 영영 안 지워지면, 다음 실행에서도 같은 자리에서 막혀 **작업이 통째로
    죽은 것과 같아진다.**

    실제로 겪었다 — 마이그레이션이 덜 적용된 판에서 ``chat_session``이 없어 앞의 두
    표까지 함께 멈췄다. 배포 순서상 **코드가 먼저 가고 마이그레이션이 뒤따르는**
    순간이 있으므로, 그 틈에서도 세션 정리는 돌아야 한다.
    """
    counts: dict[str, int] = {}
    failures: dict[str, str] = {}
    for table in _SQL:
        sql = count_sql(table, grace_days) if dry_run else delete_sql(table, grace_days)
        try:
            raw = db.query(sql)
        except QueryError as exc:
            failures[table] = str(exc).splitlines()[0] if str(exc) else "알 수 없는 실패"
            continue
        if dry_run:
            counts[table] = int(raw or 0)
        else:
            # `psql -At`의 DELETE 출력은 `DELETE <n>`이다.
            counts[table] = int(raw.rsplit(" ", 1)[-1] or 0) if raw else 0
    return counts, failures


def record(db: Db, counts: dict[str, int], failures: dict[str, str], *, grace_days: int) -> None:
    """감사 로그에 한 줄 남긴다.

    **지운 것이 없어도 남긴다** — 「돌았는데 지울 것이 없었다」와 「안 돌았다」는
    다르고, 그 차이가 곧 이 작업이 살아 있는지의 증거다(`#827` ⑵ 관측성).
    """
    details = json.dumps(
        {
            "counts": counts,
            # 실패한 표를 **기록에 남긴다** — 지운 수만 남기면 「0건」과 「못 셌다」가
            # 같아 보인다.
            "failed": sorted(failures),
            "grace_days": grace_days,
            "at": datetime.now(UTC).isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.query(
        "INSERT INTO audit_log (action, details_json) "
        f"VALUES ('{PURGE_ACTION}', $j${details}$j$::jsonb)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="만료된 세션·토큰·대화를 지운다 (#827 ⑶)")
    parser.add_argument(
        "--grace-days",
        type=int,
        default=DEFAULT_GRACE_DAYS,
        help=f"만료 뒤 더 두는 일수 (기본 {DEFAULT_GRACE_DAYS}). 채팅에는 적용하지 않는다",
    )
    parser.add_argument("--dry-run", action="store_true", help="세기만 하고 지우지 않는다")
    args = parser.parse_args(argv)

    if args.grace_days < 0:
        parser.error("--grace-days는 0 이상이어야 합니다")

    db = Db(shlex.split(os.environ.get("COMPOSE", DEFAULT_COMPOSE)))
    counts, failures = purge(db, grace_days=args.grace_days, dry_run=args.dry_run)

    verb = "지울 대상" if args.dry_run else "지웠다"
    for table in _SQL:
        if table in failures:
            print(f"{table:>14}  {'실패':>8}  {failures[table]}", file=sys.stderr)
        else:
            print(f"{table:>14}  {counts[table]:>8}  {verb}")

    if not args.dry_run:
        try:
            record(db, counts, failures, grace_days=args.grace_days)
        except QueryError as exc:
            # 기록에 실패해도 **지운 것은 이미 지워졌다.** 그 사실을 감추지 않는다.
            print(f"감사 기록 실패: {exc}", file=sys.stderr)
            return 1
    # 실패한 표가 있으면 **0을 내지 않는다** — cron이 성공으로 읽으면 아무도 모른다.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
