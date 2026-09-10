"""데모 시드가 찍는 ``cf_used``가 연료 종류의 정본 CF와 같은지 본다 (``#797``).

**막으려는 것은 계산 오류가 아니라, 원문 대조를 마친 표가 조용히 무력화되는 것이다.**

``fuel_type`` 8행은 ``MEPC.364(79)``를 출처로 갖고 마이그레이션 ``031``이
``content_hash``까지 적재해 개정을 추적한다. 그런데 실제 계산에 들어가는 것은 그 표가
아니라 **적재 시점에 얼린 스냅샷**(``cf_used``)이다. 스냅샷을 얼리는 설계 자체는 옳다 —
``PRD §8.4``가 요구하고, 규정이 개정돼도 과거 실적이 변하지 않게 한다.

문제는 **얼린 값이 처음부터 틀릴 수 있다는 것**이었다. 2026-09-05 전수 검토에서
``not_underway_fuel_use`` 6행이 ``DIESEL_GAS_OIL``인데 HFO CF(``3.114``)를 갖고 있었다.
시드가 행의 ``fuel_type``을 보지 않고 상수를 찍었기 때문이다.

**표를 아무리 정확히 관리해도 데모 값은 틀린 채로 남는다.** 그 상태를 아무도 보지
않았다 — 종전 시드 검사는 ``test_demo_seed_counts.py``의 **행 수**뿐이었다.

## 왜 「데모 시드 행만」 보는가

규정 개정 뒤의 과거 실적은 ``fuel_type.cf``와 **달라도 정상**이다(``PRD §8.4``).
전체 테이블을 훑으면 그 정당한 불일치까지 잡아 가드가 거짓 경보를 낸다.
그래서 **시드가 넣은 행**만 대조한다 — 시드는 방금 적재했으므로 개정 이력이 없고,
따라서 정본과 같아야 한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.db.demo_seed import (
    SEED_PERIOD_FUELS,
    SEED_VOYAGE_FUELS,
    clear_demo,
    seed_demo,
)

#: 시드가 넣은 행만 고른다. ``source = 'SAMPLE'``은 항차 연료 쪽 표식이고,
#: 정박 연료는 시드 상수의 ``id``로 좁힌다.
_MISMATCHED_PERIOD_FUEL = text(
    """
    SELECT u.fuel_type, u.cf_used, ft.cf
      FROM not_underway_fuel_use u
      JOIN fuel_type ft ON ft.code = u.fuel_type
     WHERE u.id = ANY(CAST(:ids AS uuid[]))
       AND u.cf_used <> ft.cf
    """
)

_MISMATCHED_VOYAGE_FUEL = text(
    """
    SELECT u.fuel_type, u.cf_used, ft.cf
      FROM voyage_fuel_use u
      JOIN fuel_type ft ON ft.code = u.fuel_type
     WHERE u.id = ANY(CAST(:ids AS uuid[]))
       AND u.cf_used <> ft.cf
    """
)


def _ids(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["id"]) for row in rows]


@pytest.mark.asyncio
async def test_정박_연료의_cf가_연료별_정본과_같다(conn: AsyncConnection):
    """`#797`의 본체. 6행이 여기서 걸렸다.

    ``SEED_PERIOD_FUELS``는 6건이 ``DIESEL_GAS_OIL``, 2건이 ``HFO``다. 종전 시드는
    **행의 종류를 보지 않고** HFO CF를 찍어, 정본 ``3.206``이어야 할 6행이 ``3.114``였다.
    """
    await clear_demo(conn)
    await seed_demo(conn)

    rows = (
        (await conn.execute(_MISMATCHED_PERIOD_FUEL, {"ids": _ids(SEED_PERIOD_FUELS)}))
        .mappings()
        .all()
    )

    assert not rows, (
        f"정박 연료 {len(rows)}행의 cf_used가 fuel_type.cf와 다릅니다:\n  "
        + "\n  ".join(f"{r['fuel_type']} 저장 {r['cf_used']} ≠ 정본 {r['cf']}" for r in rows)
    )


@pytest.mark.asyncio
async def test_항차_연료의_cf가_연료별_정본과_같다(conn: AsyncConnection):
    """항차 쪽은 종전에도 맞았다 — **맞은 채로 남는지**를 잠근다.

    이쪽은 ``fuel_type``을 함께 찍어 정합했다. 한쪽만 고치고 다른 쪽이 뒤에 어긋나는
    것을 막으려면 **둘 다** 봐야 한다.
    """
    await clear_demo(conn)
    await seed_demo(conn)

    rows = (
        (await conn.execute(_MISMATCHED_VOYAGE_FUEL, {"ids": _ids(SEED_VOYAGE_FUELS)}))
        .mappings()
        .all()
    )

    assert not rows, (
        f"항차 연료 {len(rows)}행의 cf_used가 fuel_type.cf와 다릅니다:\n  "
        + "\n  ".join(f"{r['fuel_type']} 저장 {r['cf_used']} ≠ 정본 {r['cf']}" for r in rows)
    )


def test_시드_코드에_CF_값이_직접_적혀_있지_않다():
    """값을 두 곳에 적으면 한쪽만 개정된다.

    `#797`의 원인은 시드가 **자기 상수**(``HFO_CF = Decimal("3.114000")``)를 갖고
    있던 것이다. 적재 시점에 ``fuel_type``에서 읽으면 표가 하나로 유지된다.
    상수가 되살아나면 여기서 걸린다.

    ## 두 번 헛디뎠다

    ⚠️ **문자열로 훑지 않는다.** 처음에는 소스에서 ``"3.114"``를 찾았는데 **위 문단처럼
    왜 그렇게 했는지 적은 설명이 자기 규칙에 걸렸다.** 주석 줄만 걷어내는 것으로는
    docstring이 남는다 — `#831`·`#829`·`#694`·`#928`에서 밟은 것과 같은 함정이다.

    ⚠️ **값의 범위로 판정하지도 않는다.** 다음으로 ``Decimal`` 인자가 1.3~3.3이면
    CF로 봤더니 **연료 톤수 4건**(``1.80``·``3.20``·``2.00``·``1.40``)이 걸렸다.
    같은 숫자 범위에 다른 뜻의 값이 산다.

    그래서 **이름과 키로 본다** — CF를 뜻하는 자리에 리터럴이 박혀 있는가만 묻는다.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "cii_platform" / "db" / "demo_seed.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    def is_literal(node: ast.AST) -> bool:
        """``Decimal("...")`` 또는 숫자 리터럴인가. ``cf["HFO"]`` 같은 조회는 아니다."""
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
            return True
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Decimal"
        )

    found: list[str] = []
    for node in ast.walk(tree):
        # ① CF를 이름에 담은 모듈 상수 — `HFO_CF = Decimal("3.114000")`
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and "CF" in target.id and is_literal(node.value):
                    found.append(f"{source.name}:{node.lineno}  {target.id} = <리터럴>")
        # ② `cf_used` 키에 리터럴을 직접 박은 자리
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if isinstance(key, ast.Constant) and key.value == "cf_used" and is_literal(value):
                    found.append(f"{source.name}:{node.lineno}  cf_used: <리터럴>")

    assert not found, (
        f"demo_seed.py에 CF 리터럴이 있습니다 {len(found)}건:\n  "
        + "\n  ".join(found)
        + "\n→ 적재 시점에 `fuel_type` 표에서 읽으십시오 (#797)."
    )
