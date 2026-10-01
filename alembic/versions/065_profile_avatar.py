"""프로필 이미지 — ``app_user.avatar_image`` · ``avatar_etag`` (#2080)

Revision ID: 065
Revises: 064
Create Date: 2026-10-01

왜 필요한가
-----------
이 제품이 **사용자가 올린 바이트를 남기는 첫 자리**다. 종전 업로드 둘(규정 파라미터
적재 · 항차 CSV 가져오기)은 파싱하고 **버린다**. 근거 조항은 ``PRD §5.1 [#2080]``,
열 정의는 ``DB_SCHEMA §2.15``다.

왜 BLOB이 아닌가
----------------
``sqlalchemy-cubrid``가 **자기 테스트 요건 파일에** 이렇게 적고 해당 검사를 꺼 두었다.

.. code-block:: python

    @property
    def binary_comparisons(self) -> compound:
        \"\"\"CUBRID BLOB roundtrip has driver-level issues.\"\"\"
        return _CLOSED

드라이버가 스스로 못 한다고 적은 길로 제품의 첫 이진 열을 내지 않는다. 이 저장소에는
같은 모양의 선례가 있다 — CUBRID에 JSONB가 없어 ``TEXT``에 JSON을 싣는 ``JSONText``
(``db/types.py`` · ``#1058``). 프로필 이미지는 같은 자리의 ``Base64Bytes``로 담는다.

서버가 **고정 크기 WebP로 다시 그려** 저장하므로 열 크기가 열려 있지 않다.

``avatar_etag``
---------------
바이트의 SHA-256 16진이다. ``GET``이 조건부 요청을 받았을 때 **본문을 읽지 않고**
304를 내기 위한 것이다 — 사이드바가 매 화면이라, 없으면 화면 전환마다 수십 KB를
DB에서 꺼내게 된다. 두 열은 항상 함께 채워지고 함께 비워진다.

트리거를 걸지 않는 이유
-----------------------
``064``는 값 집합이 정해진 열이라 트리거로 집행했다. 여기 두 열은 **값 집합이 없다** —
형식·크기 판정은 서버가 바이트를 디코드해 하는 일이고(``services/avatar.py``), DB가
다시 할 수 있는 검사가 아니다. 「둘이 함께 채워진다」는 관계는 서비스 한곳에서만
쓰므로 검사로 잠근다(``tests/test_avatar_db.py``).

downgrade
---------
열 둘을 지운다. 올린 이미지가 사라지지만 계산도 등급도 바뀌지 않는다
(``migration_guard`` ``REGENERABLE``) — 다시 올리면 되는 값이다.
"""

import sqlalchemy as sa

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

#: 바이트의 SHA-256 16진은 64자다 — 더도 덜도 아니다.
_ETAG_LENGTH = 64


def upgrade() -> None:
    # 타입 철자는 방언이 갖는다 — `sa.Text()`는 CUBRID에서 `STRING`으로 컴파일된다.
    # 여기 문자열로 적으면 방언과 갈릴 수 있다.
    op.add_column("app_user", sa.Column("avatar_image", sa.Text(), nullable=True))
    op.add_column(
        "app_user", sa.Column("avatar_etag", sa.String(length=_ETAG_LENGTH), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("app_user", "avatar_etag")
    op.drop_column("app_user", "avatar_image")
