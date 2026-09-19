"""기능③ 실행의 ``as_of``를 저장한다 (#816 · 결정요청 v9 회신 「가」=A안)

Revision ID: 052
Revises: 051
Create Date: 2026-09-18

왜 컬럼이 필요한가
------------------
``reproduce_annual_simulation``은 저장된 행에서 재료를 모아 ``input_hash``를 **다시
계산해 대조**한다. ``ANNUAL_INPUT_FIELDS``에 ``as_of``가 들어가면(이 이슈의 체크리스트)
**재현 시 넘길 원본 ``as_of``가 필요한데, 그 값이 어디에도 저장돼 있지 않았다** —
요청 본문으로 들어와 ``resolve_as_of()``가 확정한 뒤 그대로 버려졌다.

``NULL``은 「명시하지 않은 실행」이다 (결정요청 v9 회신)
------------------------------------------------------
해시의 ``as_of`` 키는 **명시적으로 준 실행에만** 들어간다(``apply_feedback_factor``
선례 — ``calc/hash.py``). 그러므로:

* ``NULL``  → 미명시 실행. 해시에 키가 없고, 재현도 키 없이 계산한다 — 종전 동작
* 값 있음   → 명시 실행. 해시에 키가 있고, 재현은 **이 값을 재생**해 넣는다

기존 162건의 ``input_hash``는 그대로 유지된다(전부 미명시 — 그때는 ``as_of``를 받아도
집계에 쓰지 않았으므로 미명시와 결과가 같았다).

정밀도는 ``DATETIMETZ``(밀리초)
------------------------------
``_persist``가 ``created_at``에 이미 적용하는 규칙(``#1058`` 실측 — 마이크로초는
담기지 않는다)을 ``as_of``에도 서비스 단에서 적용한다. 컬럼 타입은 다른 시각
컬럼과 같은 ``DATETIMETZ``다.
"""

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE annual_simulation_run ADD COLUMN as_of DATETIMETZ")


def downgrade() -> None:
    op.execute("ALTER TABLE annual_simulation_run DROP COLUMN as_of")
