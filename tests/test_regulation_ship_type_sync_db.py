"""두 규정 표의 선종 집합 (`#834` · IT-REG-001~005).

## 왜 필요한가

``cii_reference_line``(기준선)과 ``cii_rating_boundary``(등급 경계)는 **선종으로 짝을
이룬다.** 한쪽에만 선종이 있으면 그 선박은 반쪽 결과만 나온다.

=========================  ===============================================
 기준선만 있다              ``required_CII``는 나오는데 **등급을 못 낸다**
 경계만 있다                ``required_CII`` 자체가 안 나온다 — 등급도 무의미
=========================  ===============================================

`#834`가 **손으로** 찾아 ``RO_RO_PASSENGER_HSC`` 한 건을 드러냈다. 그때까지 아무도
몰랐던 이유는 **그 선종의 선박이 데모 선대에 없었기** 때문이다 — 코드는 정상이고
값만 비어 있으므로 어떤 검사에도 걸리지 않았다.

## 빈 것을 **목록으로 붙잡는다**

지금 빈 자리를 「고칠 때까지 실패하는 검사」로 두면, 값 판정이 규제 원문 확인
(``AGENTS §2.1``)에 달려 있는 동안 CI가 계속 빨갛다. 그렇다고 검사를 미루면 **그
사이에 같은 누락이 하나 더 늘어도 모른다.**

그래서 :data:`KNOWN_MISSING_BOUNDARY`에 **사유와 함께** 적고, 그 목록과 **정확히
같을 때만** 통과시킨다.

===================  ==========================================
 새로 생겼다           실패 — 목록에 없는 누락이다
 채워졌다              실패 — **낡은 목록은 거짓말이다**. 지운다
===================  ==========================================

`tests/moduleBoundary`(#594)·`test_api_spec_endpoints_sync`(#591)가 쓰는 것과 같은
방식이다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: 기준선은 있는데 등급 경계가 없는 선종 — **사유와 함께** 적는다.
#:
#: ⚠️ 채워지면 이 항목을 지워야 한다. 남겨 두면 검사가 거짓말한다.
KNOWN_MISSING_BOUNDARY: dict[str, str] = {
    # ⚠️ **판정은 이미 끝났다.** `PRD §3.4.4` 각주(`#126` · **원문 대조 확인
    # sky01170851**)가 정한 것은 셋이다.
    #
    # 1. `MEPC.354(78)` Table 1에 HSC 행이 **없는 것이 원문대로**다 — 전사 누락이 아니다
    # 2. **HSC의 등급 경계는 `RO_RO_PASSENGER` 행을 적용한다**
    # 3. 그래도 **시드에는 행을 추가하지 않는다** — 원문에 없는 값을 규제값 표에
    #    넣으면 `source_ref`가 거짓이 된다. 매핑은 계산 계층이 한다
    #    (`calc.rating_engine.RATING_BOUNDARY_FALLBACK`)
    #
    # 따라서 이 공백은 **의도된 것**이고 채워질 일이 없다. 아래 `IT-REG-004`가
    # **그 매핑이 실제로 동작하는지**를 본다.
    "RO_RO_PASSENGER_HSC": (
        "원문(MEPC.354(78))에 행이 없는 것이 원문대로 — 계산 계층이 "
        "RO_RO_PASSENGER를 상속한다 (PRD §3.4.4 각주 · #126)"
    ),
}


async def _ship_types(conn, table: str) -> set[str]:
    rows = await conn.execute(text(f"SELECT DISTINCT ship_type FROM {table}"))  # noqa: S608
    return {row[0] for row in rows}


async def test_no_boundary_without_a_reference_line(conn):
    """IT-REG-001 — 경계만 있고 기준선이 없는 선종은 **하나도 없어야 한다**.

    이 방향에는 예외를 두지 않는다. 기준선이 없으면 ``required_CII``가 아예 안
    나오고, 등급 경계는 ``attained/required`` 비를 자르는 값이라 **혼자서는 아무
    의미가 없다.** 그런 행이 생겼다면 시드가 잘못된 것이다.
    """
    only_boundary = await _ship_types(conn, "cii_rating_boundary") - await _ship_types(
        conn, "cii_reference_line"
    )
    assert not only_boundary, f"기준선 없는 등급 경계: {sorted(only_boundary)}"


async def test_missing_boundaries_match_the_known_list(conn):
    """IT-REG-002 — 기준선만 있는 선종이 :data:`KNOWN_MISSING_BOUNDARY`와 **정확히 같다**.

    양방향으로 깨진다 — 새 누락이 생겨도, 알려진 누락이 채워져도 실패한다.
    뒤엣것이 중요하다: **낡은 목록은 거짓말**이라, 채워진 뒤에도 남아 있으면 다음
    사람이 「아직 비어 있다」로 읽는다.
    """
    only_refline = await _ship_types(conn, "cii_reference_line") - await _ship_types(
        conn, "cii_rating_boundary"
    )
    assert only_refline == set(KNOWN_MISSING_BOUNDARY), (
        f"실측 {sorted(only_refline)} ≠ 목록 {sorted(KNOWN_MISSING_BOUNDARY)} — "
        "새 누락이면 사유와 함께 목록에 넣고, 채워졌으면 목록에서 뺄 것"
    )


async def test_every_known_gap_carries_a_reason(conn):
    """IT-REG-003 — 목록의 항목마다 **사유가 적혀 있다**.

    빈 문자열이나 「TODO」로 채우면 목록이 그저 통과용이 된다. 사유에는 **어느
    원문에 무엇이 없는지**와 이슈 번호가 들어가야 한다.
    """
    for ship_type, reason in KNOWN_MISSING_BOUNDARY.items():
        assert len(reason) >= 20, (ship_type, reason)
        assert "#" in reason, f"{ship_type}: 이슈 번호가 없다"


async def test_the_known_gap_is_covered_by_the_calc_layer_fallback(conn):
    """IT-REG-004 — ⚠️ **시드에 없는 선종이 계산 계층에서 상속받는다** (#834 · #126).

    `PRD §3.4.4` 각주가 **`RO_RO_PASSENGER` 행을 적용한다**로 정했고 원문 대조도
    끝났다(sky01170851). 시드에 행을 넣지 않는 것도 같은 각주의 결정이다 — 원문에
    없는 값을 규제값 표에 넣으면 `source_ref`가 거짓이 된다.

    그래서 **매핑이 실제로 동작하는지**가 이 공백의 유일한 방어선이다.

    ## ⚠️ 종전 이 검사는 틀린 것을 지키고 있었다

    2026-09-13 처음 쓸 때 「그 선종은 409로 거부된다」를 단언했다. **그것이 결함이었다.**
    `select_rating_boundary`는 폴백을 갖는데, 호출부가 **선종으로 걸러 조회**해서
    넘기는 바람에 폴백 대상 행이 목록에 없어 **실행될 기회조차 없었다**. 정본이 정한
    동작을 검사가 거꾸로 고정하고 있었던 것이다.
    """
    from cii_platform.calc.rating_engine import (
        RATING_BOUNDARY_FALLBACK,
        select_rating_boundary,
    )
    from cii_platform.db.repositories import parameters as param_repo

    ship_type = next(iter(KNOWN_MISSING_BOUNDARY))
    assert RATING_BOUNDARY_FALLBACK.get(ship_type), (
        f"{ship_type}이 시드에 없는데 계산 계층에 상속 대상도 없다 — 등급이 조용히 빈다"
    )

    session = AsyncSession(bind=conn)
    # ⚠️ **거르지 않고 조회한다.** 호출부가 선종으로 거르면 폴백 대상 행이 목록에
    # 없어 폴백이 죽는다 — `#834`의 실제 원인이었다.
    rows = await param_repo.list_rating_boundaries(session)
    vessel = SimpleNamespace(ship_type=ship_type, gross_tonnage=Decimal("20000"), deadweight=None)
    row = select_rating_boundary(vessel, rows)

    assert row.ship_type == RATING_BOUNDARY_FALLBACK[ship_type]


async def test_services_do_not_filter_rating_boundaries_by_ship_type(conn):
    """IT-REG-005 — ⚠️ 호출부가 **선종으로 걸러 조회하지 않는다**.

    위 폴백은 **걸러지지 않은 목록**을 전제한다(`select_rating_boundary` docstring).
    호출부가 걸러서 주면 폴백 대상 행이 없어 **폴백이 조용히 죽는다** — 그 상태가
    `#834`였고, 세 경로(기능①·기능②·YTD)가 전부 그랬다.

    소스를 훑는 이유는 **동작 검사로는 잡히지 않기 때문**이다: 걸러도 HSC가 아닌
    선박은 전부 정상이라, 데모 선대에 HSC가 없으면 아무도 모른다.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "cii_platform" / "services"
    offenders = [
        f"{path.name}:{i}"
        for path in sorted(root.glob("*.py"))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "list_rating_boundaries(session, vessel.ship_type)" in line
    ]
    assert not offenders, (
        f"선종으로 걸러 조회하는 곳: {offenders} — 걸러면 HSC 폴백이 죽는다 (#834)"
    )
