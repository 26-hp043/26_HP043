"""vessel.call_sign — 호출부호(call sign)의 저장 칸 (#1197 A단계)

Revision ID: 058
Revises: 057
Create Date: 2026-09-20

왜 필요한가
-----------
공공데이터포털의 해양수산부 계열 선박 데이터는 **IMO가 아니라 호출부호로 배를 가리킨다.**
그중 ``해양수산부_선박운항정보``(``15006353``)는 **입력 파라미터가 「항구 · 조회기간 ·
호출부호」**라 호출부호가 없으면 **질의 자체가 안 된다**(#1197 2026-09-17 코멘트 「가」).
전수 IMO ↔ 호출부호 레지스트리는 공공데이터에 없으므로(넷을 합쳐도 2천 행 남짓 · 셋이
1회성) 사용자가 자기 배의 호출부호를 넣는 칸을 ``vessel``에 둔다 — 선박국적증서·
무선국허가증에 있고 입출항 신고에 매일 쓰는 값이다.

**선택 입력**이다. 없으면 그 배는 공공데이터 교차 대조 대상이 아닐 뿐이고 계산은 그대로
된다(교차 대조는 계산 입력이 아니다 · ``TECH_SPEC §5.4``).

**UNIQUE를 걸지 않는다.** 호출부호는 국가가 **재배정**한다 — 폐선·국적 변경 뒤 같은
부호가 다른 배에 갈 수 있고, 대조는 부분 매핑으로도 결과가 난다.

값의 모양 — ITU 전파규칙 Art. 19
----------------------------------
선박국 호출부호는 ``RR No. 19.55``가 정한다 —

.. code-block:: text

    2문자 + 2문자                 (예 HLXQ    · 4자)
    2문자 + 2문자 + 1숫자          (예 HLXQ7   · 5자)
    2문자(둘째는 문자) + 4숫자     (예 3F1234  · 6자)
    2문자 + 1문자 + 4숫자          (예 KRA1234 · 7자)

앞 두 문자는 국가 배정 계열(``RR No. 19.50``)이며 **둘 다 숫자일 수 없다.** 그래서 길이는
**4~7자**, 문자는 **영문 대문자와 숫자**뿐이다.

DB 트리거는 ``^[A-Z0-9]{4,7}$``만 본다
-------------------------------------------
- 「앞 두 글자가 모두 숫자가 아니다」와 「문자 바로 뒤에 0·1이 오지 않는다」(``19.50``의
  세부)는 **API 스키마가 앞 것만** 본다(``api/schemas/vessel.py``). 배정 관행이 나라마다
  달라 세부 규칙까지 DB에 박으면 실재하는 부호를 거부할 수 있다 — 이 칸은 **대조용 키**이지
  인증서가 아니다.
- ``BINARY``를 붙인다 — CUBRID의 ``REGEXP``는 기본이 대소문자 무시라(``050`` 실측)
  소문자가 들어와 대조 키가 갈린다. 정규화(strip · upper)는 API가 하고 DB는 결과만 받는다.
- 집행은 트리거다(CUBRID는 CHECK를 보관조차 하지 않는다 · ``DB_SCHEMA §7.4``). 이름
  규칙은 ``046``·``055``와 같다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

_TABLE = "vessel"
_COLUMN = "call_sign"

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

#: ``{4,7}`` 수량자와 ``BINARY``가 CUBRID 11.4에서 기대대로 동작하는 것을 실측했다
#: (``HLXQ``·``D5AB123`` 통과 · ``ABC``·``ABCDEFGH``·``hlxq``·``HL-XQ``·``HLXQ `` 거부).
_CONDITION = f"new.{_COLUMN} IS NULL OR new.{_COLUMN} REGEXP BINARY '^[A-Z0-9]{{4,7}}$'"


def _trigger_name(event: str) -> str:
    return f"trg_chk_call_sign_{event.lower()[:3]}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(7)")
    # 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
    for event in _EVENTS:
        create_trigger(
            op,
            _trigger_name(event),
            f"BEFORE {event} ON {_TABLE} IF NOT ({_CONDITION}) EXECUTE REJECT",
        )


def downgrade() -> None:
    """건 것만 되돌린다 — 데이터는 한 행도 바꾸지 않는다(구조만 REGENERABLE).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    for event in _EVENTS:
        drop_trigger(op, _trigger_name(event))
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}")
