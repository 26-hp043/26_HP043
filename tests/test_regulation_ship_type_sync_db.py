"""두 규정 표의 선종 집합 (`#834` · IT-REG-001~004).

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

from sqlalchemy import text

#: 기준선은 있는데 등급 경계가 없는 선종 — **사유와 함께** 적는다.
#:
#: ⚠️ 채워지면 이 항목을 지워야 한다. 남겨 두면 검사가 거짓말한다.
KNOWN_MISSING_BOUNDARY: dict[str, str] = {
    # `MEPC.354(78)`(G4 등급 경계)에 High-speed craft 행이 **따로 없다.** 기준선
    # 쪽(`MEPC.353(78)` G2)은 HSC를 별도 행으로 두고 있어 두 표의 구분 단위가
    # 다르다. 「G4의 Ro-ro passenger ship 행이 HSC를 포함하는가」와 「HSC가 등급
    # 대상이 아닌가」 중 어느 쪽인지는 **원문 해석**이라 팀원 확인이 필요하다
    # (`AGENTS §2.1`). 그 확인 전까지 값을 지어내지 않는다 — 지어낸 등급 경계는
    # 틀렸다는 사실이 화면에 드러나지 않는다.
    "RO_RO_PASSENGER_HSC": "MEPC.354(78)에 HSC 행 부재 — 원문 해석 확인 대기 (#834)",
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


async def test_missing_boundary_fails_loudly_not_silently(conn):
    """IT-REG-004 — 경계가 없는 선박은 **409로 분명히 거부**된다.

    `#834`가 *"500인지, 경고와 함께 `rating: null`인지, 조용히 빈 값인지"*를 물었다.
    실측 결과는 ``PARAMETER_ERROR``(HTTP 409)이고 문구에 **선종 이름이 들어간다.**

    이 셋의 차이가 중요하다.

    ==================  =================================================
     500                 우리 버그처럼 보인다 — 원인 추적이 코드로 간다
     조용한 `null`        화면이 「등급 없음」으로 그려 **값이 없는 것처럼** 보인다
     **409 + 선종 이름**  규정 파라미터가 없다는 사실이 그대로 전달된다
    ==================  =================================================

    가운데 것이 가장 나쁘다 — `#653`이 총톤수 누락에서 겪은 것과 같은 모양이다.
    그래서 「조용해지지 않는 것」을 단언으로 고정한다.
    """
    from decimal import Decimal
    from uuid import uuid4

    from cii_platform.errors import ParameterError
    from cii_platform.services.voyage_cii import (
        FuelUseInput,
        VoyageCiiInput,
        estimate_voyage_cii,
    )

    ship_type = next(iter(KNOWN_MISSING_BOUNDARY))
    imo = f"9{uuid4().int % 1_000_000:06d}"
    vessel_id = (
        await conn.execute(
            text(
                "INSERT INTO vessel (name, imo_number, ship_type, deadweight, gross_tonnage) "
                "VALUES ('IT-REG-004', :imo, :st, 5000, 12000) RETURNING id"
            ),
            {"imo": imo, "st": ship_type},
        )
    ).scalar_one()

    from sqlalchemy.ext.asyncio import AsyncSession

    session = AsyncSession(bind=conn)
    try:
        await estimate_voyage_cii(
            session,
            VoyageCiiInput(
                vessel_id=vessel_id,
                regulation_year=2026,
                distance_nm=Decimal("1000"),
                speed_kn=Decimal("20"),
                fuel_uses=(FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("80")),),
            ),
        )
        raise AssertionError("등급 경계가 없는데 계산이 성공했다")
    except ParameterError as exc:
        assert exc.http_status == 409, exc.http_status
        # 선종 이름이 문구에 있어야 **어느 선종이 빈지**를 말할 수 있다.
        assert ship_type in exc.message, exc.message
