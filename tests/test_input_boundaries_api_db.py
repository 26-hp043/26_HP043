"""입력 경계 3종의 HTTP 계약 (``#818``).

**막으려는 것은 계산 오류가 아니라, 같은 입력에 엔드포인트마다 다르게 답하는 것이다.**

세 자리 모두 **같은 저장소의 다른 엔드포인트가 이미 옳게 처리하는 입력**이었다.
규율이 갈린 자리이므로 「어느 쪽이 맞나」가 아니라 「왜 갈렸나」가 질문이다.

.. code-block:: text

    ⑴ year=2019 연간 리포트   →  422   (사용자가 보낸 적 없는 `from` 필드에 대한 422)
    ⑵ limit=-2 항차 목록      →  500   (선박·계산 목록은 422)
    ⑶ ship_type 변경          →  재계산 표시 없음  (DWT/GT 변경은 남긴다)

## 데이터를 남기지 않는다

``TestClient``는 **실제로 커밋한다.** 전용 선박을 만들고 ``finally``에서 지운다 —
남기면 다음 실행의 선대 집계와 리포트가 이 행들을 본다.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _seed_vessel() -> str:
    from cii_platform.db.session import get_sessionmaker

    vessel_id = uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'BOUNDARY TEST', 'BULK_CARRIER', "
                "50000, 'HFO')"
            ),
            {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
        )
        await s.commit()
    return str(vessel_id)


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text("DELETE FROM calculation_run WHERE vessel_id = :v"), {"v": UUID(vessel_id)}
        )
        await s.execute(text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": UUID(vessel_id)})
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": UUID(vessel_id)})
        await s.commit()


async def test_연간_리포트가_2019년에도_생성된다(migrated_db, app_fresh_engine):
    """⑴ — ``API_SPEC §2.13``이 ``year`` 2019~2100을 유효로 정한다.

    종전에는 **422**였다. 리포트가 최근 3년 창을 만들려고 ``from = year - 2 = 2017``을
    파생시켰고, ``§2.7``의 ``from ≥ 2019`` 검증이 그 파생값에 걸렸다.

    **사용자가 보낸 적 없는 필드에 대한 422**다. 창을 좁혀 해결한다 — 오류를 삼켜
    이력을 비우면 **2019년 리포트에서 2019년 행까지 사라진다.**
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            for year in (2019, 2020, 2021):
                response = client.get(
                    f"/api/v1/vessels/{vessel_id}/annual-report",
                    params={"year": year, "format": "html"},
                )
                assert response.status_code == 200, f"{year}: {response.text}"
    finally:
        await _cleanup(vessel_id)


async def test_항차_목록_limit이_선박_목록과_같은_422를_낸다(migrated_db, app_fresh_engine):
    """⑵ — 세 서비스가 같은 규칙을 각자 적었고 **항차만 빠져 있었다**.

    ``limit=-2``는 ``.limit(-1)``이 되어 PostgreSQL이 거부했고(**500**), ``limit=-1``은
    0행인데 ``has_more=true``·``next_cursor=null``이라 **따라갈 커서가 없는 「다음
    페이지」**를 냈으며, ``limit=0``은 조용히 20건이었다.
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            for bad in (-2, -1, 0):
                voyages = client.get(f"/api/v1/vessels/{vessel_id}/voyages", params={"limit": bad})
                vessels = client.get("/api/v1/vessels", params={"limit": bad})
                assert voyages.status_code == 422, f"limit={bad}: {voyages.text}"
                # 같은 입력에 같은 답을 내야 한다 — 이 검사의 요지다.
                assert voyages.status_code == vessels.status_code, (
                    f"limit={bad}: 항차 {voyages.status_code} ≠ 선박 {vessels.status_code}"
                )
    finally:
        await _cleanup(vessel_id)


async def test_항차_목록_limit_상한은_오류가_아니라_절단이다(migrated_db, app_fresh_engine):
    """상한 초과를 422로 만들지 않는 정책이 유지되는지 함께 본다.

    하한만 보면 **상한도 막는 방향으로 잘못 고칠 수 있다.** 큰 ``limit``은 공격이
    아니라 오해인 경우가 대부분이고, 422를 내면 클라이언트가 재시도 로직을 따로
    만들어야 한다.
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.get(f"/api/v1/vessels/{vessel_id}/voyages", params={"limit": 100_000})
            assert response.status_code == 200, response.text
    finally:
        await _cleanup(vessel_id)


async def test_선종_변경이_재계산_표시를_남긴다(conn):
    """⑶ — 선종은 **capacity 축·기준선 a/c·등급 경계 d1~d4를 전부** 바꾼다.

    DWT/GT 변경보다 영향이 큰데 표시가 없었다. ``BULK_CARRIER → TANKER``로 고치면
    과거 ``calculation_run``이 전부 ``needs_recalc=false``인 채 **유효한 것처럼 남았다.**

    ## 왜 이 하나만 HTTP가 아닌가

    ``calculation_run``은 **immutable 테이블**이다(``008``·``024`` 가드). 행을 넣으면
    수정도 삭제도 막히므로, ``TestClient``로 검사하면 **정리할 수 없는 행이 DB에 남는다.**
    결함 자체도 ``services/vessel.py``에 있어 서비스 계층이 맞는 자리다 —
    롤백 픽스처(``conn``)를 쓰면 흔적이 남지 않는다.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.services.vessel import create_vessel, update_vessel

    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        marker = uuid4()
        created = await create_vessel(
            db,
            imo_number=f"9{marker.int % 1000000:06d}",
            name="BOUNDARY SHIP TYPE",
            ship_type="BULK_CARRIER",
            deadweight=50000,
            default_fuel_type="HFO",
        )
        vessel_id = UUID(str(created["id"]))

        await db.execute(
            text(
                "INSERT INTO calculation_run (id, vessel_id, calculation_type, "
                "input_hash, parameter_hash, result_json, parameters_used, "
                "model_version, needs_recalc) VALUES (:id, :v, 'VOYAGE_ESTIMATE', "
                "'sha256:" + "0" * 64 + "', 'sha256:" + "1" * 64 + "', "
                "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, false)"
            ),
            {"id": uuid4(), "v": vessel_id},
        )

        before = (
            await db.execute(
                text("SELECT count(*) FROM calculation_run WHERE vessel_id = :v AND needs_recalc"),
                {"v": vessel_id},
            )
        ).scalar_one()
        assert before == 0, "사전 조건: 아직 표시가 없어야 한다"

        await update_vessel(db, vessel_id, ship_type="TANKER")

        after = (
            await db.execute(
                text("SELECT count(*) FROM calculation_run WHERE vessel_id = :v AND needs_recalc"),
                {"v": vessel_id},
            )
        ).scalar_one()
        assert after == 1, "선종을 바꿨는데 재계산 표시가 남지 않았습니다"
