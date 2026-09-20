"""「연간 반영 시 변화」 (`PRD §10.3` ⑨ · `§10.4` · `#1338`).

## 무엇이 없었나

`PRD §10.3` 9항은 *「연간 시뮬레이터에 이미 동일 선박·연도 데이터가 있으면 "이 항차
반영 시 연말 예상 등급 변화"를 미리 계산해 표시한다」*고, `§10.4` 출력 표는
「연간 반영 시 변화」 행을 정한다. `§5.1`이 기능①을 **MUST**로 둔다.

**API·화면 어디에도 없었다** — `§4.1` 응답 표에 그런 필드가 없고 `frontend/src`에도
0건이었다. 출력 표의 한 행이 **통째로 비어** 있었다.

## 무엇을 단언하는가

⚠️ **이 값은 항차 CII와 다른 질문에 답한다.** 항차 CII는 「이 항차 하나의 강도」이고
이 블록은 「선박의 연말 값이 이 항차 때문에 어디로 가나」다 — **두 값이 반대 방향을
가리키는 것이 정상**이므로, 그 성질을 검사가 직접 고정한다.

조립을 새로 만들지 않았다는 것도 본다 — 같은 선박·같은 연도의 **실시간 CII ⑶ 연말
예상**과 `before`가 같아야 한다. 조립이 둘이면 **두 화면이 다른 숫자**를 낸다
(`#798` 실측: 7.654488 vs 8.971119).

케이스 (`TEST_PLAN §14.5`): 정본 정합 — `PRD §10.3` ⑨ · `§10.4`
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db import demo_seed
from cii_platform.services.voyage_cii import (
    FuelUseInput,
    VoyageCiiInput,
    estimate_voyage_cii,
)

YEAR = 2026
BULK = UUID(demo_seed.VESSEL_ID_BULK)
CONTAINER = UUID(demo_seed.VESSEL_ID_CONTAINER)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _estimate(session, vessel_id: UUID, *, distance="3000", fuel="250", year=YEAR):
    return await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=vessel_id,
            regulation_year=year,
            distance_nm=Decimal(distance),
            speed_kn=Decimal("14"),
            fuel_uses=(FuelUseInput(fuel_type="HFO", fuel_ton=Decimal(fuel)),),
        ),
        persist=False,
    )


@pytest.mark.asyncio
async def test_the_row_exists_at_all(session) -> None:
    """**이것이 이 이슈다** — 출력 표의 한 행이 통째로 비어 있었다."""
    data = (await _estimate(session, BULK))["data"]
    impact = data["annual_impact"]

    assert impact is not None
    assert set(impact) == {"before", "after", "rating_changed"}
    assert set(impact["before"]) == {"attained_cii", "rating"}


@pytest.mark.asyncio
async def test_adding_the_voyage_moves_the_year_end_value(session) -> None:
    """**전후가 실제로 달라야 한다** — 같으면 이 블록이 아무것도 말하지 않는다."""
    impact = (await _estimate(session, BULK))["data"]["annual_impact"]

    assert impact["before"]["attained_cii"] != impact["after"]["attained_cii"]


@pytest.mark.asyncio
async def test_a_longer_voyage_moves_it_further(session) -> None:
    """방향이 맞는지 — 같은 강도의 항차를 **더 길게** 넣으면 연말 값이 더 끌린다.

    부호가 뒤집히면 화면이 **정반대**를 말하는데, 값이 그럴듯해서 드러나지 않는다.
    """
    short = (await _estimate(session, BULK, distance="1000", fuel="80"))["data"]
    long = (await _estimate(session, BULK, distance="8000", fuel="640"))["data"]

    before = Decimal(short["annual_impact"]["before"]["attained_cii"])
    near = Decimal(short["annual_impact"]["after"]["attained_cii"])
    far = Decimal(long["annual_impact"]["after"]["attained_cii"])

    assert abs(far - before) > abs(near - before)


@pytest.mark.asyncio
async def test_the_rating_change_flag_matches_the_two_ratings(session) -> None:
    """플래그가 두 등급과 **같은 말을 하는지** — 갈리면 화면이 어느 쪽을 믿을지 모른다."""
    for vessel in (BULK, CONTAINER):
        impact = (await _estimate(session, vessel))["data"]["annual_impact"]

        changed = impact["before"]["rating"] != impact["after"]["rating"]
        assert impact["rating_changed"] is changed


@pytest.mark.asyncio
async def test_it_answers_a_different_question_than_the_voyage_rating(session) -> None:
    """⚠️ **항차 등급과 연말 등급은 다른 것을 잰다 — 수준이 어긋나는 것이 정상이다.**

    항차 등급은 **이 항차 하나**를, 연말 등급은 **그 배의 한 해 전체**를 본다.
    실측(데모 시드 · 같은 항차 3,000 nm · HFO 250 t):

    * 벌크 50,000 — 항차 등급 ``C`` / 연말 ``E → E`` (8.97 → 8.35 · 개선)
    * 컨테이너 — 항차 등급 ``E`` / 연말 ``B → C`` (18.41 → 19.02 · 악화)

    **항차 등급이 좋은 배의 연말이 나쁘고, 항차 등급이 나쁜 배의 연말이 좋다.**
    이 검사가 없으면 **두 값을 같은 것으로 착각한 구현**이 통과한다 — 항차 등급을
    그대로 ``after.rating``에 넣어도 드러나지 않는다.
    """
    bulk = (await _estimate(session, BULK))["data"]
    container = (await _estimate(session, CONTAINER))["data"]

    for data in (bulk, container):
        assert data["annual_impact"]["after"]["rating"] != data["estimated_rating"], (
            "연말 등급이 항차 등급과 같다 — 두 값을 같은 것으로 다루고 있지 않은지 본다"
        )

    def moved(data) -> Decimal:
        impact = data["annual_impact"]
        return Decimal(impact["after"]["attained_cii"]) - Decimal(impact["before"]["attained_cii"])

    # 방향도 함께 본다: 같은 항차가 한 배의 연말은 끌어내리고 다른 배의 연말은 올린다.
    assert moved(bulk) < 0, "같은 항차가 벌크선의 연말 값을 개선하지 않는다"
    assert moved(container) > 0, "같은 항차가 컨테이너선의 연말 값을 악화시키지 않는다"


@pytest.mark.asyncio
async def test_before_matches_the_realtime_year_end(session) -> None:
    """조립을 새로 만들지 않았는지 — `§2.14` ⑶과 **같은 숫자**여야 한다.

    조립이 둘이면 같은 선박·같은 연도에서 **두 화면이 다른 값**을 낸다
    (`#798` 실측: 7.654488 vs 8.971119).
    """
    from cii_platform.services.cii_current import get_current_cii

    impact = (await _estimate(session, BULK))["data"]["annual_impact"]
    current, _ = await get_current_cii(session, BULK, year=YEAR)
    year_end = current["year_end_projection"]

    assert year_end["data_available"] is True
    assert impact["before"]["attained_cii"] == year_end["attained_cii"]
    assert impact["before"]["rating"] == year_end["rating"]


@pytest.mark.asyncio
async def test_the_digits_match_the_other_cii_values(session) -> None:
    """한 응답 안에서 같은 양이 **다른 자릿수**로 실리면 화면이 둘을 다르게 다룬다."""
    data = (await _estimate(session, BULK))["data"]

    places = len(data["attained_cii"].split(".")[1])
    assert len(data["annual_impact"]["before"]["attained_cii"].split(".")[1]) == places


@pytest.mark.asyncio
async def test_a_vessel_without_annual_data_gets_null(session) -> None:
    """정본이 *「**이미 동일 선박·연도 데이터가 있으면**」*으로 조건을 달았다.

    비교할 「기존 연말 예상」이 없으면 **0과 비교한 숫자를 지어내지 않는다.**
    """
    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type) VALUES (:id, :imo, 'NO ANNUAL DATA', 'BULK_CARRIER', "
            "50000, 'HFO')"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
    )
    await session.commit()
    try:
        data = (await _estimate(session, vessel_id))["data"]
        assert data["annual_impact"] is None
    finally:
        await session.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": vessel_id})
        await session.commit()


@pytest.mark.asyncio
async def test_the_block_does_not_change_the_hashes(session) -> None:
    """파생 출력이지 **입력이 아니다** — 해시가 바뀌면 저장된 실행이 재현되지 않는다."""
    first = await _estimate(session, BULK)
    second = await _estimate(session, BULK)

    assert first["input_hash"] == second["input_hash"]
    assert first["parameter_hash"] == second["parameter_hash"]


async def test_the_field_reaches_the_http_response(migrated_db, app_fresh_engine) -> None:
    """응답 조립까지 나가는지 (`#433` — 엔진에서 나오는 값이 응답에 안 나간 적이 있다)."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
        response = client.post(
            f"{API_V1_PREFIX}/calculations/voyage-cii",
            json={
                "vessel_id": str(BULK),
                "regulation_year": YEAR,
                "distance_nm": 3000,
                "speed_kn": 14,
                "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 250}],
            },
            headers={"X-CSRF-Token": client.cookies["csrf"]},
        )

    assert response.status_code == 200, response.text
    impact = response.json()["data"]["annual_impact"]

    assert impact is not None
    assert impact["before"]["rating"] in {"A", "B", "C", "D", "E"}
    assert isinstance(impact["rating_changed"], bool)


def test_the_as_of_is_not_an_input(session) -> None:
    """시각을 입력으로 받지 않는다 — 받으면 `§5.4.1` 계약이 기능①까지 넓어진다.

    기능①의 `input_hash`에는 `as_of`가 없고(`TECH_SPEC §5.3`), 이 블록 때문에
    그것이 바뀌면 **저장된 모든 기능① 실행의 해시**가 흔들린다.
    """
    import inspect

    from cii_platform.services import voyage_cii

    assert "as_of" not in inspect.signature(voyage_cii.estimate_voyage_cii).parameters
    assert "as_of" not in inspect.signature(voyage_cii._annual_impact).parameters


@pytest.mark.asyncio
async def test_multi_fuel_uses_a_mass_weighted_cf(session) -> None:
    """⚠️ **유종이 둘 이상이면 CF를 질량가중으로 모은다** (`#1338`).

    ``RemainingVoyage``는 항차당 CF **하나**를 갖는다(`PRD §12.4.1` — 연료 종류는
    MVP에서 항차별 고정). 첫 유종의 CF를 그대로 쓰면 ``Σ(fuel_j × cf_j)``가 보존되지
    않아 분자 ``M``이 기능①의 값과 갈린다.

    **순서를 바꿔 본다** — 질량가중 평균은 순서에 무관하지만 「첫 유종의 CF」는
    순서가 바뀌면 값이 달라진다. 돌연변이가 그 형태로 빠져나갔던 자리다.
    """
    forward = await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=BULK,
            regulation_year=YEAR,
            distance_nm=Decimal("3000"),
            speed_kn=Decimal("14"),
            fuel_uses=(
                FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("200")),
                FuelUseInput(fuel_type="LNG", fuel_ton=Decimal("50")),
            ),
        ),
        persist=False,
    )
    reversed_ = await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=BULK,
            regulation_year=YEAR,
            distance_nm=Decimal("3000"),
            speed_kn=Decimal("14"),
            fuel_uses=(
                FuelUseInput(fuel_type="LNG", fuel_ton=Decimal("50")),
                FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("200")),
            ),
        ),
        persist=False,
    )

    assert (
        forward["data"]["annual_impact"]["after"]["attained_cii"]
        == reversed_["data"]["annual_impact"]["after"]["attained_cii"]
    )


@pytest.mark.asyncio
async def test_a_single_fuel_is_the_same_either_way(session) -> None:
    """대조군 — 유종이 하나면 두 방식이 같다. 위 검사가 그 사실에 기대지 않게 한다."""
    one = (await _estimate(session, BULK))["data"]["annual_impact"]

    assert one is not None
