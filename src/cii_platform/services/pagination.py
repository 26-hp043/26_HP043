"""목록 조회의 ``limit`` 정규화 (``API_SPEC §1.9``).

## 왜 공용으로 두는가

같은 규칙이 **세 곳에 각자 적혀 있었고, 그중 하나만 빠져 있었다** (``#818`` ⑵).

.. code-block:: text

    services/vessel.py       1 미만 → 422 · 상한 초과 → 절단
    services/calculation.py  1 미만 → 422 · 상한 초과 → 절단
    services/voyage.py       min(limit or DEFAULT, MAX)      ← 아무것도 막지 않는다

빠진 자리에서 무슨 일이 났는가.

.. code-block:: text

    limit=-2   →  .limit(-1)  →  PostgreSQL "LIMIT must not be negative"  →  500
    limit=-1   →  .limit(0)   →  0행인데 has_more=true, next_cursor=null
                                 → 따라갈 커서가 없는 「다음 페이지」
    limit=0    →  0 or 20     →  조용히 20건

**규칙을 세 번 적으면 세 번째가 빠진다.** 한 곳에 두고 상·하한만 받는다.

## 정책

- **상한 초과는 오류로 만들지 않고 잘라 낸다.** 목록 조회에서 큰 ``limit``은 공격이
  아니라 오해인 경우가 대부분이고, 422를 내면 클라이언트가 재시도 로직을 따로
  만들어야 한다. 상한을 넘겨도 상한만큼은 정상 응답한다
- **1 미만(0·음수)은 422다.** 0건 페이지는 의미가 없어 오타로 본다
"""

from __future__ import annotations

from cii_platform.errors import ValidationError


def normalize_limit(limit: int | None, *, default: int, maximum: int) -> int:
    """``limit``을 ``[1, maximum]``으로 정규화한다.

    :param limit: 요청값. ``None``이면 ``default``.
    :param default: 미지정 시 쓰는 값.
    :param maximum: 상한. 초과분은 **오류가 아니라 절단**이다.
    :raises ValidationError: ``limit``이 1 미만일 때.
    """
    if limit is None:
        return default
    if limit < 1:
        raise ValidationError(
            "limit은 1 이상이어야 합니다.", field="limit", field_label="페이지 크기"
        )
    return min(limit, maximum)
