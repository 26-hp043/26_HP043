"""활성 키 열 + 유니크 인덱스 — 동시 등록에서도 활성 행의 IMO·이메일이 유일하게 (#1631)

Revision ID: 061
Revises: 060
Create Date: 2026-09-24

무엇이 막혀 있었나
------------------
``047``은 ``vessel.imo_number``·``app_user.email``의 「활성 행 안에서만 유일」을 **트리거**
(``trg_uq_*_active_ins``·``_upd`` — ``BEFORE INSERT/UPDATE … IF NOT (… NOT EXISTS …) EXECUTE
REJECT``)로 옮겼다. CUBRID가 부분 유니크 인덱스를 만들지 못하기 때문이었다.

그런데 트리거 안의 ``NOT EXISTS``는 **일반 ``SELECT``와 같은 READ COMMITTED 스냅샷**을 본다
(`#1796` 실측). 두 요청이 같은 IMO를 거의 동시에 넣으면 서로의 미커밋 행을 보지 못해
**둘 다 통과**하고, 같은 IMO 행이 조용히 두 개 남는다 — 예외조차 나지 않는다. 앱의
사전 조회(``find_active_by_imo`` · 가입의 ``is_deleted == 0`` 조회)도 같은 스냅샷을 보므로
같은 이유로 못 막는다. 실측이다 (`#1631` 2026-09-23 코멘트)::

    두 연결로 같은 IMO를 동시에 INSERT (047 트리거 + 비유일 인덱스)
    결과: ['B:ok', 'A:ok'] · 남은 행: 2

**유니크 인덱스는 다르다.** 뒤 INSERT가 앞 트랜잭션의 커밋까지 **대기**한 뒤 위반으로
떨어진다 — 격리 수준과 무관하게 DB가 강제한다(`#1796` ⑸ 대조군 · 3/3에서 1행).

무엇을 하는가 (F-9 안 「가」 · 2026-09-22 결정)
-----------------------------------------------
CUBRID가 못 하는 형태(부분 유일)를 CUBRID가 하는 형태(**별도 열의 통짜 유일**)로 옮긴다.
**순서가 있다** — 중복부터 세고, ``047`` 트리거를 걷고, 열을 만들고, 백필하고, 인덱스를
세운다.

0. **사전 검사 — 아무것도 바꾸기 전에 두 표의 활성 중복 그룹을 센다.** ``047`` 시절의
   경합이 남긴 같은 키의 활성 행이 하나라도 있으면 **여기서 예외로 멈추고 DB는 그대로다**
   (``047`` 트리거도 남아 있다 · 열도 인덱스도 만들지 않는다). 메시지는 표별 그룹 수와
   ``docs/OPERATIONS.md`` §3.6.4의 절차만 적고 **값(IMO·이메일)은 적지 않는다** — 배포
   로그가 공개 저장소의 Actions에 남기 때문이다. 사람이 미리 운영 DB를 조회할 필요가
   없다 — 마이그레이션이 먼저 세고, 중복이면 멈춘다(``#1631`` G-1 결정 「다′」 ·
   2026-09-24). 조용히 한쪽을 지우지 않는다 — 무엇을 남길지는 사람이 정한다.
1. ``047``의 트리거 4개를 **걷는다** (아래 「걷는 이유」). 백필 ``UPDATE``가 그 트리거
   (``BEFORE UPDATE … REJECT``)를 타므로 열·백필보다 앞에 둔다.
2. **활성 키 열**을 둔다 — ``vessel.imo_active VARCHAR(7)`` · ``app_user.email_active
   VARCHAR(320)``. 활성 행이면 원본 열의 사본, 소프트 삭제된 행이면 ``NULL``.
3. 기존 행을 **백필**한다 — ``CASE WHEN is_deleted = 0 THEN <원본> ELSE NULL END``.
4. 그 열에 **``CREATE UNIQUE INDEX``**를 건다. CUBRID 유니크 인덱스는 NULL을 여러 개
   허용한다 — 빈 표로 실측했다(NULL 3행 INSERT OK · 값→NULL 뒤 같은 값 재INSERT OK ·
   같은 값 두 번은 ``errno=-670``). 그래서 삭제된 행이 몇 개든 같은 키를 다시 쓸 수 있고,
   활성 행끼리만 유일하다 — 부분 유니크 인덱스와 같은 뜻이다. 0에서 중복이 없음을 확인한
   뒤이므로 이 문장이 중복으로 서는 것은 0과 4 사이의 몇 초 안에 옛 백엔드(배포는 마이그레이션
   뒤에 백엔드를 바꾼다 · ``docs/OPERATIONS.md`` §3.1)가 같은 키를 동시에 두 번 넣는 경합이
   겹칠 때뿐이다. 그때도 조용히 지우지 않는다 — 사람이 §3.6.4로 정리하고 다시 돌린다.
5. 값은 **앱이 아니라 DB가 유지한다.** ``AFTER INSERT``·``AFTER UPDATE`` 트리거가 방금
   쓰인 행을 ``is_deleted``에 따라 다시 채운다. 앱·시드·수동 SQL 어느 경로로 써도 같다.

중간에 멈춘 뒤 다시 돌릴 수 있다
--------------------------------
중복은 0에서 걸리므로 그때는 되돌릴 것이 없다 — 중복을 정리한 뒤 ``alembic upgrade head``를
그대로 다시 돌리면 된다. 다른 이유(연결 끊김 등)로 1~5 사이에서 멈출 수는 있다. CUBRID
DDL이 트랜잭션에 묶이는지는 실측하지 않았으므로 **각 단계가 카탈로그를 먼저 보고 이미
있으면 건너뛴다** — 트리거는 공용 헬퍼 ``db/trigger_ddl.py``(``#1373`` — ``db_trigger``를
보고 있으면 만들지 않고 없으면 지우지 않는다), 열·인덱스는 ``db_attribute`` · ``db_index``를
같은 형태로 본다. 백필은 멱등이다(같은 값을 다시 쓴다).

왜 ``BEFORE``가 아니라 ``AFTER`` + 자기 행 ``UPDATE``인가
-------------------------------------------------------
CUBRID 트리거에는 MySQL의 ``SET new.col = …``이 없다. ``BEFORE INSERT``에서 ``new``를
갱신하는 형태(``UPDATE t SET … WHERE t = new``)는 REUSE_OID 표라 컴파일이 거부된다 —
실측이다::

    CREATE TRIGGER … BEFORE INSERT ON t EXECUTE UPDATE t SET imo_active = … WHERE t = new
    → The class 'dba.t' is marked as REUSE_OID and is non-referable.

그래서 행이 들어간 **뒤에** ``obj``(방금 쓰인 행)를 ``WHERE id = obj.id``로 다시 갱신한다.
그 갱신이 다시 ``AFTER UPDATE`` 트리거를 부르지만, **이미 맞는 값이면 ``IF``가 거짓**이라
한 번에 멈춘다(재귀 방지). 빈 표로 여섯 경우를 확인했다::

    ① 첫 등록                 OK  → imo_active = imo
    ② 같은 IMO 활성 중복      오류 (트리거 액션 안의 유니크 위반 · errno=-528)
    ③ 소프트 삭제             OK  → imo_active = NULL
    ④ 같은 IMO 재등록         OK
    ⑤ 무관한 열만 UPDATE      OK  (IF 거짓 — 자기 갱신 없음)
    ⑥ 삭제된 행 되살리기      오류 ← 그 사이 IMO를 남이 가져갔다 (047의 ⑥과 같다)
    ⑦ imo_active를 엉뚱하게 넣은 INSERT → 트리거가 바로잡는다 (DB가 값을 소유한다)
    두 연결 교차(A insert → B insert → A commit): B가 A 커밋까지 ≈1s 대기 후 오류 · 1행 (3/3)

``updated_at``은 건드리지 않는다 — 자기 갱신과 백필이 ``SET updated_at = <지금 값>``을
함께 적어 ``049``의 열 속성 ``ON UPDATE CURRENT_DATETIME``이 시각을 밀지 않게 한다.

어떤 예외로 오는가
------------------
유니크 위반이 **트리거 액션 안에서** 나므로 드라이버는 ``-670``이 아니라 **``-528``**
(``Error evaluating action for "dba.trg_…", Operation would have caused one or more unique
constraint violations. INDEX uq_vessel_imo_active …``)로 올린다. ``db/cubrid_errors.py``가
이 번호를 유니크 위반 메시지와 함께 ``IntegrityError``로 옮기고, 인덱스 이름을
``violated_unique_index()``로 집는다 — 회원가입 라우트와 ``create_vessel``이 그 이름으로
**중복만** 골라 기존 409 문구로 바꾼다. 다른 무결성 위반은 그대로 올라간다.

``047`` 트리거를 걷는 이유
-------------------------
같은 불변식에 집행 장치가 둘이면 오류 서명도 둘이 된다(``-517`` 트리거 거부 / ``-528``
유니크). 게다가 ``047``의 ``NOT EXISTS``는 **이 이슈가 실측으로 깨뜨린 바로 그 검사**다 —
경합에서 통과시키는 검사를 「유일성을 지킨다」는 이름으로 남겨 두면 다음 사람이 그것을
믿는다. 쓰기마다 드는 서브쿼리 비용도 없앤다. downgrade가 원문 그대로 되살린다.

downgrade
---------
트리거·인덱스·열을 걷고 ``047`` 트리거를 다시 만든다. **데이터를 한 행도 지우지 않는다.**
열의 값은 ``is_deleted``와 원본 열에서 **결정적으로** 다시 나오므로(백필이 같은 값을
채운다) ``migration_guard.REGENERABLE``이다 — ``052``·``053``과 달리 값 자체가 재생된다.
upgrade와 같은 이유로 각 단계가 카탈로그를 보고 없으면 건너뛴다.

``op.drop_index``·``op.add_column``을 쓰지 않는다 — alembic이 내는 ``DROP INDEX <이름>``은
PostgreSQL 문법이고 CUBRID는 표를 함께 적어야 한다(``047`` 실측). 짝이 되는 문장이 같은
자리에서 읽히도록 전부 생 SQL로 적는다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


#: (테이블, 원본 열, 활성 키 열, 활성 키 열 타입, 유니크 인덱스, 047 트리거 앞머리).
#:
#: 유니크 인덱스 이름(``uq_<표>_<열>_active``)은 ``db/cubrid_errors.violated_unique_index``가
#: 드라이버 메시지에서 집어 라우트·서비스가 「중복인가」를 가르는 키다. 바꾸면 그 둘도
#: 함께 바꾼다 (``services/vessel.py`` · ``api/routes/auth.py``).
ACTIVE_KEYS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "vessel",
        "imo_number",
        "imo_active",
        "VARCHAR(7)",
        "uq_vessel_imo_active",
        "trg_uq_vessel_imo_active",
    ),
    (
        "app_user",
        "email",
        "email_active",
        "VARCHAR(320)",
        "uq_app_user_email_active",
        "trg_uq_app_user_email_active",
    ),
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _fill_trigger_name(table: str, active: str, event: str) -> str:
    """``046``·``054``의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자."""
    return f"trg_{table}_{active}_{event.lower()[:3]}"


def _legacy_trigger_name(prefix: str, event: str) -> str:
    """``047``이 만든 이름 그대로."""
    return f"{prefix}_{event.lower()[:3]}"


def _expected(source: str) -> str:
    """활성 키 열이 가져야 하는 값 — 활성이면 원본, 삭제면 NULL."""
    return f"CASE WHEN obj.is_deleted = 0 THEN obj.{source} ELSE NULL END"


def _needs_fill(source: str, active: str) -> str:
    """지금 값이 기대와 다른가. 같으면 거짓이라 자기 갱신이 한 번에 멈춘다(재귀 방지).

    ``is_deleted``는 CUBRID에서 SHORT라 ``= 0``·``<> 0``으로 비교한다(``047``).
    """
    return (
        f"(obj.is_deleted = 0 AND (obj.{active} IS NULL OR obj.{active} <> obj.{source})) "
        f"OR (obj.is_deleted <> 0 AND obj.{active} IS NOT NULL)"
    )


def _legacy_condition(table: str, column: str) -> str:
    """``047``의 조건 원문 — downgrade가 그 트리거를 그대로 되살린다."""
    return (
        f"new.is_deleted <> 0 OR NOT EXISTS ("
        f"SELECT 1 FROM {table} t WHERE t.{column} = new.{column} "
        f"AND t.is_deleted = 0 AND t.id <> new.id)"
    )


# --- 카탈로그 조회 — 중간에 멈춘 뒤 다시 돌려도 이미 한 단계는 건너뛴다 ---------------
#
# 트리거는 공용 헬퍼 ``db/trigger_ddl.py``(`#1373` — 있으면 만들지 않고, 없으면 지우지
# 않는다)가 ``db_trigger``를 본다. 열·인덱스는 헬퍼가 없어 여기서 같은 형태로 본다.


class ActiveDuplicatesError(RuntimeError):
    """활성 행 안에 같은 키가 둘 이상 있어 ``061``을 적용하지 않았다 — DB는 그대로다."""


def duplicate_message(groups: dict[str, int]) -> str:
    """사전 검사가 멈출 때의 문구. ``groups``는 ``{"vessel.imo_number": 2, …}`` 형태.

    **값(IMO·이메일)은 넣지 않는다** — 이 문구는 배포 워크플로의 로그로 나가고, 그 로그는
    공개 저장소의 Actions에 남는다. 그룹 수와 절차만 적는다. 호출자가 아니라 여기서
    문구를 조립하는 것은 DB 없이 검사하기 위해서다(``tests/test_active_key_precheck.py``).
    """
    counted = " · ".join(f"{key} {count}개" for key, count in groups.items())
    return (
        "마이그레이션 061을 적용하지 않았다 — 활성 행 안에 같은 키가 둘 이상인 그룹이 있다"
        f"({counted}). DB는 그대로다(047 트리거도 남아 있고 열·인덱스도 만들지 않았다). "
        "docs/OPERATIONS.md §3.6.4의 절차로 남길 행을 정해 나머지를 소프트 삭제한 뒤 "
        "`alembic upgrade head`를 다시 돌린다. 어느 값인지는 이 문구에 적지 않는다 — "
        "배포 로그가 공개 저장소에 남는다."
    )


def _duplicate_group_count(table: str, source: str) -> int:
    """활성 행(``is_deleted = 0``) 안에서 같은 ``source`` 값을 가진 그룹의 수.

    값 자체는 고르지 않는다 — 결과가 문구로 나가므로 수만 센다.
    """
    return int(
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT {source} FROM {table} WHERE is_deleted = 0 "
                f"GROUP BY {source} HAVING COUNT(*) > 1) t"
            )
        )
        .scalar_one()
    )


def _assert_no_active_duplicates() -> None:
    """0단계 — 두 표를 세고, 하나라도 중복이면 아무것도 바꾸기 전에 멈춘다."""
    groups = {
        f"{table}.{source}": _duplicate_group_count(table, source)
        for table, source, *_ in ACTIVE_KEYS
    }
    if any(groups.values()):
        raise ActiveDuplicatesError(duplicate_message(groups))


def _column_exists(table: str, column: str) -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM db_attribute WHERE class_name = :t AND attr_name = :c"),
            {"t": table, "c": column},
        )
        .first()
    )
    return row is not None


def _index_exists(table: str, index: str) -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM db_index WHERE class_name = :t AND index_name = :i"),
            {"t": table, "i": index},
        )
        .first()
    )
    return row is not None


def upgrade() -> None:
    # 0) 사전 검사 — 아무것도 바꾸기 전에 두 표의 활성 중복 그룹을 센다. 하나라도 있으면
    #    예외로 멈추고 DB는 그대로다(047 트리거 유지 · 열·인덱스 없음). 사람이 미리 조회할
    #    필요가 없다 — 절차는 docs/OPERATIONS.md §3.6.4.
    _assert_no_active_duplicates()
    have = existing_triggers(op)
    for table, source, active, sql_type, index_name, legacy_prefix in ACTIVE_KEYS:
        # 1) 047의 트리거를 걷는다 — 아래 백필 UPDATE가 `_upd`(BEFORE UPDATE … REJECT)를
        #    타므로 열·백필보다 앞에 둔다. 없으면 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
        for event in _EVENTS:
            drop_trigger(op, _legacy_trigger_name(legacy_prefix, event), existing=have)
        # 2) 활성 키 열
        if not _column_exists(table, active):
            op.execute(f"ALTER TABLE {table} ADD COLUMN {active} {sql_type}")
        # 3) 백필 — 기존 행. 멱등이다(같은 값을 다시 쓴다). `updated_at = updated_at`은
        #    049의 ON UPDATE 열 속성이 시각을 밀지 않게 하는 것이다(값은 그대로).
        op.execute(
            f"UPDATE {table} SET {active} = CASE WHEN is_deleted = 0 THEN {source} ELSE NULL END, "
            f"updated_at = updated_at"
        )
        # 4) 유니크 인덱스. 중복은 0)에서 걸렀다 — 여기서 서는 것은 0)과 4) 사이 몇 초에 옛
        #    백엔드의 경합이 겹칠 때뿐이고, 그때도 조용히 지우지 않는다(§3.6.4로 정리 뒤 재실행).
        if not _index_exists(table, index_name):
            op.execute(f"CREATE UNIQUE INDEX {index_name} ON {table} ({active})")
        # 5) 채움 트리거 — 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
        for event in _EVENTS:
            create_trigger(
                op,
                _fill_trigger_name(table, active, event),
                f"AFTER {event} ON {table} "
                f"IF {_needs_fill(source, active)} "
                f"EXECUTE UPDATE {table} SET {active} = {_expected(source)}, "
                f"updated_at = obj.updated_at WHERE id = obj.id",
                existing=have,
            )


def downgrade() -> None:
    """건 것을 걷고 ``047``의 트리거를 되살린다 — 데이터는 한 행도 바꾸지 않는다.

    없는 것은 지우지 않고, 있는 것은 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    have = existing_triggers(op)
    for table, source, active, _sql_type, index_name, legacy_prefix in ACTIVE_KEYS:
        for event in _EVENTS:
            drop_trigger(op, _fill_trigger_name(table, active, event), existing=have)
        if _index_exists(table, index_name):
            op.execute(f"DROP INDEX {index_name} ON {table}")
        if _column_exists(table, active):
            op.execute(f"ALTER TABLE {table} DROP COLUMN {active}")
        # 047 원문 그대로 — 열·인덱스가 사라진 뒤에 되살린다(백필 순서의 역).
        for event in _EVENTS:
            create_trigger(
                op,
                _legacy_trigger_name(legacy_prefix, event),
                f"BEFORE {event} ON {table} "
                f"IF NOT ({_legacy_condition(table, source)}) EXECUTE REJECT",
                existing=have,
            )
