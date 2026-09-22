"""외부에서 받는 시각 타입 (`API_SPEC §1.7` · `#1627`).

## 시간대를 요구한다

``datetime``을 그대로 쓰면 Pydantic이 ``2026-06-01T09:00``처럼 **시간대 없는 값**을
받아들이고, 그 값은 **읽는 쪽이 어디냐에 따라 다른 순간**이 된다. 배포 호스트의
시간대가 바뀌면 같은 요청이 다른 항차 순서·다른 연간 귀속·다른 ``as_of`` 경계를
만든다 — 재현성이 호스트 설정에 달리게 된다.

``not_underway`` 스키마가 `#1333`에서 같은 이유로 ``AwareDatetime``을 택했고, CSV
경로(``services/voyage_import._instant``)는 처음부터 시간대를 요구했다. **한 리소스의
입구마다 규칙이 다르면** 어느 쪽으로 들어왔는지에 따라 저장된 값이 달라진다.

## 받은 뒤 UTC로 맞춘다

시간대가 붙어 있으면 ``+09:00``이든 ``Z``든 같은 순간이지만, **저장·비교 전에 UTC로
맞춰** 두면 로그·응답·`input_hash`에서 같은 순간이 언제나 같은 문자열이 된다.
``astimezone(UTC)``는 순간을 바꾸지 않는다 — 표기만 옮긴다.

화면은 이미 UTC(``toISOString()``)로 보낸다(``frontend/src/features/voyage-management/
voyageRules.ts``의 ``toIsoInstant``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime


def _to_utc(value: datetime) -> datetime:
    """시간대가 붙은 시각을 UTC 표기로 옮긴다. 순간은 그대로다."""
    return value.astimezone(UTC)


#: 외부 JSON이 주는 시각. 시간대가 없으면 422(`VALIDATION_ERROR`), 있으면 UTC로 맞춘다.
Instant = Annotated[AwareDatetime, AfterValidator(_to_utc)]
