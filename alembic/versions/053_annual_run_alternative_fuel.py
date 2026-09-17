"""기능③ 실행의 대체 연료 선택을 저장한다 (#756 ⑴ · 결정요청 v9 회신 「나」)

Revision ID: 053
Revises: 052
Create Date: 2026-09-18

왜 컬럼이 필요한가
------------------
대체 연료 지렛대는 **사용자가 요청에서 고른 연료**에 따라 결과가 달라진다(질량 유지
— 연료량 고정, CF만 교체). 그 선택이 ``input_hash``의 선택 키가 되므로(#816 ⑴의
``as_of``와 같은 세 번째 적용례), 재현은 **원본 실행이 고른 연료**를 다시 넘겨야
한다 — 그 값이 어디에도 저장돼 있지 않으면 재현의 해시 대조가 성립하지 않는다.

``NULL``은 「고르지 않은 실행」
------------------------------
미지정 실행에는 해시 키가 없고(``_filter_fields``가 건너뛴다) 블록도 나가지
않는다. 기존 실행의 ``input_hash``는 무변경이다. ``as_of``(052)와 같은 규약이다.

값은 ``fuel_type.fuel_code``(``String(30)``)다 — CF는 저장하지 않는다. 재현이
**지금 활성 CF**로 다시 계산하므로, CF 개정이 있으면 결과·해시가 어긋나야 하는
것이 이 지렛대의 존재 이유다(#816 ⑶ ``fuel_types`` 블록과 같은 규율).
"""

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE annual_simulation_run ADD COLUMN alternative_fuel VARCHAR(30)")


def downgrade() -> None:
    op.execute("ALTER TABLE annual_simulation_run DROP COLUMN alternative_fuel")
