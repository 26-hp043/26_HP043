"""참조 중인 연료 코드의 부모 DELETE를 막는다 (#2308).

Revision ID: 069
Revises: 068
Create Date: 2026-10-09

fuel_type 시드가 #2086 이후 UPDATE/INSERT를 사용하므로 REPLACE의 DELETE 때문에
보호를 제외했던 사유가 사라졌다. 자식 세 참조 중 하나라도 남으면 부모 삭제를
거부한다. 삭제된 자식도 이력이므로 포함하며, 참조가 없는 연료는 삭제할 수 있다.
CF/활성/판본 UPDATE와 068의 코드 개명 보호는 유지한다. 데이터는 바꾸지 않는다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None

# 참조 정합 거부다. immutable 분류의 _no_delete 표식을 사용하지 않는다.
TRIGGER_NAME = "trg_fuel_type_referenced_delete"
TRIGGER_BODY = (
    "BEFORE DELETE ON fuel_type IF "
    "EXISTS (SELECT 1 FROM vessel WHERE default_fuel_type = obj.code) OR "
    "EXISTS (SELECT 1 FROM voyage_fuel_use WHERE fuel_type = obj.code) OR "
    "EXISTS (SELECT 1 FROM not_underway_fuel_use WHERE fuel_type = obj.code) "
    "EXECUTE REJECT"
)


def upgrade() -> None:
    """이미 있으면 건너뛰고 참조 중인 부모 삭제 보호를 건다."""
    create_trigger(op, TRIGGER_NAME, TRIGGER_BODY)


def downgrade() -> None:
    """트리거만 걷는다. 참조/시드/계산 데이터는 바꾸지 않는다."""
    drop_trigger(op, TRIGGER_NAME)
