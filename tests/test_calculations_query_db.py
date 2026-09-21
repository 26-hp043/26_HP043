"""GET /calculations DB 실동작 테스트 (#56) — hash 조회·keyset 페이지네이션.

계약 테스트(``test_calculations_api.py``)가 저장소를 대역으로 쓰는 반면, 여기는
**실제 쿼리**를 검증한다 — hash 정확 일치, 필터 AND 결합, ``(created_at desc,
id desc)`` 정렬, 커서 페이지네이션.

``calculation_run``은 immutable이라 cleanup에서 트리거를 잠시 끈다
(``test_voyage_delete_db.py``와 같은 패턴). 인증은 dev-login 실제 흐름으로
통과한다(배선 #307).

케이스: AT-CQ-001 · AT-CQ-003 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

VALID_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


async def _insert_vessel(session, imo: str) -> str:
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type) "
        "VALUES (:imo, 'CALC QUERY TEST', 'BULK_CARRIER') RETURNING id",
        {"imo": imo},
    )


async def _insert_run(
    session,
    vessel_id: str,
    *,
    input_hash: str,
    parameter_hash: str,
    calculation_type: str = "VOYAGE_ESTIMATE",
    needs_recalc: bool = False,
) -> str:
    # JSON 값은 파라미터로 바인딩한다 — 리터럴 안에 ':1' 같은 열쇠가 있으면 text()가
    # bind parameter로 오해해 파싱이 깨진다. 종전 `CAST(:param AS jsonb)`는 PostgreSQL
    # 시절 모양이라 CUBRID 변환기가 떼어 내고 있었다 — 변환기가 치환을 멈춰(#1316) 걷었다.
    return await insert_returning_id(
        session,
        "INSERT INTO calculation_run "
        "(calculation_type, vessel_id, voyage_id, "
        " input_hash, parameter_hash, model_version, result_json, parameters_used, "
        " needs_recalc) "
        "VALUES (:ctype, :vid, NULL, :ih, :ph, "
        " :mv, :rj, '{}'::jsonb, :nr) RETURNING id",
        {
            "ctype": calculation_type,
            "vid": vessel_id,
            "ih": input_hash,
            "ph": parameter_hash,
            "mv": '{"major": 1}',
            "rj": '{"attained_cii": "4.9824", "estimated_rating": "C"}',
            # 가드 트리거(024)가 true→false 되돌림을 막으므로 INSERT에서 세운다.
            "nr": 1 if needs_recalc else 0,
        },
    )


async def _cleanup(session, vessel_id: str) -> None:
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 정리를 위해 잠시 끄고
    # 즉시 복구한다.
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.commit()


async def _delete_stub_user() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


async def test_hash_pair_exact_match(migrated_db, app_fresh_engine):
    """input_hash + parameter_hash → 정확히 일치하는 행만 (§1.9 재현성 용법)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s, "7100101")
            await _insert_run(s, vessel_id, input_hash=VALID_HASH, parameter_hash=VALID_HASH)
            await _insert_run(s, vessel_id, input_hash=OTHER_HASH, parameter_hash=VALID_HASH)
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            resp = client.get(
                "/api/v1/calculations",
                params={"input_hash": VALID_HASH, "parameter_hash": VALID_HASH},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["input_hash"] == VALID_HASH
        assert data[0]["result_summary"] == {
            "attained_cii": "4.9824",
            "estimated_rating": "C",
        }
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_type_and_vessel_filters_and_pagination(migrated_db, app_fresh_engine):
    """type·vessel_id 필터 + keyset 페이지네이션 (최신 먼저)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s, "7100202")
            # 3건의 VOYAGE_ESTIMATE + 1건의 다른 타입.
            for i in range(3):
                await _insert_run(
                    s,
                    vessel_id,
                    input_hash=f"sha256:{i:064d}",
                    parameter_hash=VALID_HASH,
                )
            await _insert_run(
                s,
                vessel_id,
                input_hash=OTHER_HASH,
                parameter_hash=OTHER_HASH,
                calculation_type="SCENARIO",
            )
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            # type 필터 — VOYAGE_ESTIMATE만 3건.
            resp = client.get(
                "/api/v1/calculations",
                params={"type": "VOYAGE_ESTIMATE", "vessel_id": vessel_id},
            )
            assert resp.status_code == 200
            assert len(resp.json()["data"]) == 3
            assert all(d["calculation_type"] == "VOYAGE_ESTIMATE" for d in resp.json()["data"])

            # 페이지네이션 — limit=2 → 2건 + has_more, 커서로 나머지 1건.
            page1 = client.get(
                "/api/v1/calculations",
                params={"type": "VOYAGE_ESTIMATE", "vessel_id": vessel_id, "limit": 2},
            ).json()
            assert len(page1["data"]) == 2
            assert page1["meta"]["has_more"] is True
            assert page1["meta"]["next_cursor"]

            page2 = client.get(
                "/api/v1/calculations",
                params={
                    "type": "VOYAGE_ESTIMATE",
                    "vessel_id": vessel_id,
                    "limit": 2,
                    "cursor": page1["meta"]["next_cursor"],
                },
            ).json()
            assert len(page2["data"]) == 1
            assert page2["meta"]["has_more"] is False

            # 두 페이지를 합치면 중복이 없다 (keyset의 핵심 보장).
            ids1 = {d["calculation_run_id"] for d in page1["data"]}
            ids2 = {d["calculation_run_id"] for d in page2["data"]}
            assert ids1 & ids2 == set()
            assert len(ids1 | ids2) == 3
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_needs_recalc_total_counts_the_filter_not_the_page(migrated_db, app_fresh_engine):
    """``meta.needs_recalc_total``은 **받은 페이지가 아니라 필터 전체**를 센다 (#1076).

    선박 상세의 「계산 이력」이 머리에 「재계산 필요 N건」을 적는데, 종전에는 화면이
    **받은 20건만** 세었다. 21번째 행부터 낡아 있으면 머리에 **「0건」**이 찍혀
    「낡은 계산이 없다」와 「아직 다 세어 보지 않았다」가 같은 모양이 됐다.

    그래서 여기서 박는 것은 세 가지다 — ⑴ 페이지 크기보다 큰 수가 나오는가
    ⑵ 페이지를 넘겨도 값이 변하지 않는가 ⑶ ``type`` 필터를 따라가는가.
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s, "7100203")
            # VOYAGE_ESTIMATE 3건 중 2건이 낡았다.
            for i in range(3):
                await _insert_run(
                    s,
                    vessel_id,
                    input_hash=f"sha256:{i:064d}",
                    parameter_hash=VALID_HASH,
                    needs_recalc=i < 2,
                )
            # 다른 종류의 낡은 계산 1건 — `type` 필터가 이것을 빼야 한다.
            await _insert_run(
                s,
                vessel_id,
                input_hash=OTHER_HASH,
                parameter_hash=OTHER_HASH,
                calculation_type="SCENARIO",
                needs_recalc=True,
            )
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            base = {"type": "VOYAGE_ESTIMATE", "vessel_id": vessel_id, "limit": 1}
            page1 = client.get("/api/v1/calculations", params=base).json()

            # ⑴ 한 건만 받았는데 2가 나온다 — 받은 페이지를 셌다면 1이었다.
            assert len(page1["data"]) == 1
            assert page1["meta"]["needs_recalc_total"] == 2

            # ⑵ 다음 페이지에서도 같다. 페이지마다 달라지면 화면이 그 수를
            #    「이 선박의 낡은 계산 수」로 말할 수 없다.
            page2 = client.get(
                "/api/v1/calculations",
                params={**base, "cursor": page1["meta"]["next_cursor"]},
            ).json()
            assert page2["meta"]["needs_recalc_total"] == 2

            # ⑶ 종류를 풀면 SCENARIO 1건이 더해진다 — 필터를 따라간다.
            all_types = client.get("/api/v1/calculations", params={"vessel_id": vessel_id}).json()
            assert all_types["meta"]["needs_recalc_total"] == 3
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


def test_unauthenticated_is_401(migrated_db, app_fresh_engine):
    """세션 없는 조회는 401 — 배선(#307)이 이 라우트도 보호한다."""
    with TestClient(app, base_url=_BASE) as client:
        resp = client.get("/api/v1/calculations")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"
