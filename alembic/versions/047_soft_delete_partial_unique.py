"""소프트 삭제된 행이 유일성 검사에서 빠지게 되돌린다 (`#1058`)

Revision ID: 047
Revises: 046
Create Date: 2026-09-16

무엇이 막혀 있었나
------------------
PostgreSQL 시절 ``vessel.imo_number``와 ``app_user.email``의 유일성은 **부분 유니크
인덱스**로 걸려 있었다.

    CREATE UNIQUE INDEX idx_vessel_imo ON vessel (imo_number)
      WHERE is_deleted = false

「**지워지지 않은 행 안에서만** 유일」이라는 뜻이다. 전환이 조건을 떼고 통짜 UNIQUE로
옮기면서, **지운 행도 유일성 검사에 계속 참여**하게 됐다.

**CUBRID에 filtered index가 있기는 하다. 그러나 UNIQUE와 함께 쓸 수 없다** — 빈
테이블로 네 조합을 재 확인했다::

    CREATE UNIQUE INDEX … ON t (imo) WHERE is_deleted = 0
      → Syntax: invalid create index
    CREATE UNIQUE INDEX … ON t (imo, is_deleted) WHERE is_deleted = 0
      → Syntax: invalid create index          ← 필터 열을 키에 넣어도 같다
    CREATE INDEX … ON t (imo) WHERE is_deleted = 0
      → Semantic: Invalid filter expression   ← 필터 열이 키에 없으면 거부
    CREATE INDEX … ON t (imo, is_deleted) WHERE is_deleted = 0
      → OK                                    ← **비유일일 때만** 선다

즉 「조건이 붙는 인덱스」로는 **유일성을 걸 수 없다.** 조회 최적화에는 쓸 수 있으나
이 리비전이 되살리려는 것은 유일성이므로 길이 아니다.

사용자에게 그대로 보이는 동작이다.

* 선박을 지웠다가 **같은 IMO로 다시 등록** → 거부된다. 그 IMO는 영영 못 쓴다.
* 탈퇴한 사용자가 **같은 이메일로 재가입** → 거부된다.

「지웠다」고 화면이 말해 놓고 그 값을 다시 쓸 수 없으므로, 사용자는 **무엇이 남아
있는지 알 방법이 없다.** 소프트 삭제를 쓰는 이유(감사 로그·계산 이력이 그 행을
참조하므로 지우지 않고 표시만 한다 — ``DB_SCHEMA §7.1``) 자체가 성립하지 않는다.

정본이 규정한 완료 기준이기도 하다 — ``#52``의 「soft delete 후 동일 IMO 재등록
가능」(``services/vessel.py:312``), ``auth.py:554``·``schemas/auth.py:80``이 그 인덱스를
부분 유일로 적고 있다. **문서와 코드 주석은 부분 유일이라 말하는데 DB만 아니었다.**

무엇을 하는가
-------------
``a7d3e9b14f26``·``046``과 **같은 판단**이다 — CUBRID가 못 하는 제약은 트리거로 옮겨
**DB에서 실제로 막는다.**

1. 통짜 UNIQUE 인덱스를 **비유일 인덱스로 바꾼다.** 조회 경로(``repositories/vessel.py``
   의 IMO 조회, 로그인의 email 조회)가 그대로 인덱스를 타게 남긴다.
2. INSERT·UPDATE에 트리거를 걸어 **활성 행끼리만** 유일하게 한다.

왜 키에 표식을 붙이지 않는가
----------------------------
삭제할 때 ``imo_number``를 ``9330001#deleted#<ts>``처럼 바꾸면 스키마를 손대지 않고도
같은 결과를 얻는다. 그러나 **원본 IMO가 사라진다** — 감사 로그에서 「어느 배였나」를
잃는다. 소프트 삭제의 목적이 「기록은 남긴다」인데 기록을 고쳐 버리면 남긴 뜻이 없다.

자기 자신은 세지 않는다
-----------------------
``UPDATE``에서 ``EXISTS``가 **갱신 대상 행 자신**을 세면, 이름만 바꾸는 갱신도
거부된다. ``v.id <> new.id``로 자신을 뺀다. 빈 테이블로 여섯 경우를 확인했다::

    ① 첫 등록                 OK
    ② 같은 IMO 활성 중복      rejected
    ③ 소프트 삭제             OK
    ④ 같은 IMO 재등록         OK      ← 이 리비전이 되살리는 것
    ⑤ 무관한 열만 UPDATE      OK      ← 자기 자신을 세면 여기서 깨진다
    ⑥ 삭제된 행 되살리기      rejected ← 그 사이 IMO를 남이 가져갔다

⑥은 의도한 동작이다. 되살리려는 행의 IMO를 이미 활성 행이 쓰고 있으면 **두 활성 행이
같은 IMO를 갖게 되므로** 막아야 한다.

``op.drop_index``를 쓰지 않는다
------------------------------
alembic이 내는 ``DROP INDEX <이름>``은 PostgreSQL 문법이다. **CUBRID는 테이블을 함께
적어야 한다** — 실측이다::

    DROP INDEX idx_vessel_imo
    → Syntax: unexpected END OF STATEMENT (errno=-493, description='Table not found')

``DROP INDEX <이름> ON <테이블>``로 직접 적는다. 짝이 되는 ``CREATE INDEX``도 같은
자리에서 읽히도록 생 SQL로 맞춘다.

``is_deleted``는 BOOLEAN이 아니라 SMALLINT다
--------------------------------------------
CUBRID에서 ``sa.Boolean()``은 SMALLINT로 내려간다(``a7d3e9b14f26``이 ``needs_recalc``
에서 같은 것을 확인했다). 그래서 ``= 0``·``<> 0``으로 비교한다.
"""

from __future__ import annotations

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


#: (트리거 앞머리, 테이블, 유일해야 하는 열, 인덱스 이름).
#:
#: 앞머리가 ``trg_uq_``인 것은 ``cubrid_errors``가 이 거부를 ``IntegrityError``로
#: 옮기는 표식이다 — PostgreSQL의 UNIQUE 위반과 같은 갈래로 받게 한다.
PARTIAL_UNIQUES: tuple[tuple[str, str, str, str], ...] = (
    ("trg_uq_vessel_imo_active", "vessel", "imo_number", "idx_vessel_imo"),
    ("trg_uq_app_user_email_active", "app_user", "email", "idx_app_user_email"),
)


def _condition(table: str, column: str) -> str:
    """활성 행 안에서만 유일한가. 삭제된 행은 언제나 통과한다."""
    return (
        f"new.is_deleted <> 0 OR NOT EXISTS ("
        f"SELECT 1 FROM {table} t WHERE t.{column} = new.{column} "
        f"AND t.is_deleted = 0 AND t.id <> new.id)"
    )


def upgrade() -> None:
    """통짜 UNIQUE를 비유일 인덱스로 바꾸고, 활성 행 유일성을 트리거로 건다."""
    for prefix, table, column, index_name in PARTIAL_UNIQUES:
        op.execute(f"DROP INDEX {index_name} ON {table}")
        op.execute(f"CREATE INDEX {index_name} ON {table} ({column})")
        for event in ("INSERT", "UPDATE"):
            op.execute(
                f"CREATE TRIGGER {prefix}_{event.lower()[:3]} BEFORE {event} ON {table} "
                f"IF NOT ({_condition(table, column)}) EXECUTE REJECT"
            )


def downgrade() -> None:
    """트리거를 떼고 통짜 UNIQUE로 되돌린다.

    **데이터를 한 행도 지우지 않는다** — ``migration_guard``의 세 분류 어디에도 넣지
    않고 ``guard_irreversible_downgrade``도 부르지 않는다(``a7d3e9b14f26``·``046``과
    같은 판단).

    ⚠️ 되돌린 뒤에는 **소프트 삭제된 행과 활성 행이 같은 키를 갖는 상태**가 통짜
    UNIQUE를 위반한다. 그런 행이 이미 있으면 ``create_index``가 그 자리에서 실패한다 —
    조용히 한쪽을 지우지 않는다. 지우는 것은 데이터 손실이고, 무엇을 지울지는
    사람이 정할 일이다.
    """
    for prefix, table, column, index_name in PARTIAL_UNIQUES:
        for event in ("INSERT", "UPDATE"):
            op.execute(f"DROP TRIGGER {prefix}_{event.lower()[:3]}")
        op.execute(f"DROP INDEX {index_name} ON {table}")
        op.execute(f"CREATE UNIQUE INDEX {index_name} ON {table} ({column})")
