"""YTD 「항차 수」가 같은 표의 누적 거리·연료와 모순되지 않는가 (``#800``).

**막으려는 것은 값 오류가 아니라, 한 표 안에서 앞뒤가 맞지 않는 것이다.**

진행 중 항차의 기여분은 거리·연료에 더해지는데 ``voyage_count``는 올라가지 않았다.
연간 실적 리포트에서 이렇게 나왔다.

.. code-block:: text

    누적 거리 (nm) 5,985    ← 4,300(완료) + 1,685(진행 중) = 항차 2개
    항차 수        1        ← 진행 중 항차를 세지 않는다

5,985 nm를 1항차로 나누면 항차당 5,985 nm인데 실제 완료 항차는 4,300 nm다. 사람이
검산하면 여기서 걸린다.

## ``voyage_count``의 뜻은 바꾸지 않는다

``API_SPEC §2.7``이 이미 **「실적 확정 항차 수 · 진행 중 항차는 세지 않는다」**로 정해
두었다. 그 뜻을 뒤집으면 확정 이력(과거 연도)과 올해가 다른 것을 센다. 대신 **누적에
들어간 진행분을 따로 센다** — ``in_progress_voyage_count``.

데모 선박 ``VESSEL_ID_BULK``는 올해 완료 항차와 진행 중 항차를 함께 갖는다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.demo_seed import VESSEL_ID_BULK

_BASE = "https://testserver"


def _get(client: TestClient, path: str) -> dict:
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_진행_중_항차가_누적에_들어가면_따로_센다(migrated_db, app_fresh_engine):
    """``cii/current``와 ``cii-history`` 올해 행이 **같은 필드를 같은 뜻**으로 낸다."""
    with TestClient(app, base_url=_BASE) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 200
        current = _get(client, f"/vessels/{VESSEL_ID_BULK}/cii/current")
        history = _get(client, f"/vessels/{VESSEL_ID_BULK}/cii-history")

    assert current["current_voyage"] is not None, (
        "사전 조건: 데모 선박에 진행 중 항차가 있어야 한다"
    )
    this_year = max(row["regulation_year"] for row in history["years"])
    row = next(r for r in history["years"] if r["regulation_year"] == this_year)

    assert current["ytd"]["in_progress_voyage_count"] == 1
    assert row["in_progress_voyage_count"] == 1
    # 확정 항차 수의 뜻은 그대로다 — 두 경로가 같은 값을 낸다.
    assert current["ytd"]["voyage_count"] == row["voyage_count"]


def test_지난_연도_행에는_진행분이_없다(migrated_db, app_fresh_engine):
    """진행 중 항차는 **그 항차가 선언한 연도에만** 들어간다 (`#750` · `#815`).

    다른 해에 1이 찍히면 그 해에는 없던 항차가 확정 이력을 흔드는 것처럼 읽힌다.
    """
    with TestClient(app, base_url=_BASE) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 200
        history = _get(client, f"/vessels/{VESSEL_ID_BULK}/cii-history")

    this_year = max(row["regulation_year"] for row in history["years"])
    past = [r for r in history["years"] if r["regulation_year"] < this_year]
    assert past, "사전 조건: 비교할 지난 연도가 있어야 한다"
    assert all(r["in_progress_voyage_count"] == 0 for r in past)


def test_연간_리포트가_완료_항차와_진행_중_항차를_갈라_적는다(migrated_db, app_fresh_engine):
    """리포트 한 표 안에서 거리·연료와 항차 수가 검산된다.

    종전 라벨 「항차 수」는 두 항차의 거리를 1항차로 읽게 했다.
    """
    with TestClient(app, base_url=_BASE) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 200
        response = client.get(
            f"/api/v1/vessels/{VESSEL_ID_BULK}/annual-report", params={"format": "html"}
        )
    assert response.status_code == 200, response.text
    html = response.text

    assert "완료 항차 수" in html
    assert "진행 중 항차 (거리·연료에 포함)" in html
    # 연도별 추이 표의 올해 행도 진행분을 함께 적는다.
    assert "(+진행 중 1)" in html
    # 종전 라벨이 남아 있으면 같은 표에 두 뜻이 섞인다.
    assert ">항차 수<" not in html
