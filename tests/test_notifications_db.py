"""알림 — 지금 걸려 있는 상태 목록 (`API_SPEC §2.19` · #2204).

## 무엇을 잠그나

알림은 **새 판정이 아니다** — 선대 요약(`§2.8`) · 데이터 점검(`§2.16`)이 이미 내는 판정을
모은 것이다. 그래서 가장 중요한 단언은 **두 출처와 수가 같다**는 것이다. 한쪽만 고쳐 갈리면
대시보드의 「조치 필요」와 종 버튼의 수가 다르게 보이고, 화면은 깨지지 않아 늦게 발견된다.

데모 시드 위에서 HTTP로 받는다 — 시드의 값에 기대지 않고 **같은 요청 시각의 두 출처와
대조**한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app

_BASE = "https://testserver"
YEAR = 2026
AS_OF = "2026-10-06T00:00:00Z"

ITEM_KEYS = {
    "kind",
    "level",
    "vessel_id",
    "vessel_name",
    "reason",
    "days",
    "voyage_id",
    "voyage_no",
    "count",
}
KIND_ORDER = ["CORRECTIVE_ACTION", "D_ENTRY_SOON", "UNCONFIRMED_VOYAGE", "ESTIMATED_VALUES"]


def _get(client: TestClient, path: str) -> dict:
    response = client.get(f"{API_V1_PREFIX}{path}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_route_answers_over_http(migrated_db, app_fresh_engine):
    """인증 · 봉투 · 키 집합 · 422 — 서비스 검사는 라우트 배선을 보지 않는다."""
    with TestClient(app, base_url=_BASE) as client:
        assert client.get(f"{API_V1_PREFIX}/fleet/notifications").status_code == 401

        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        body = _get(client, f"/fleet/notifications?regulation_year={YEAR}&as_of={AS_OF}")
        assert set(body) == {"data", "meta"}
        data = body["data"]
        assert set(data) == {"as_of", "regulation_year", "counts", "items"}
        assert data["regulation_year"] == YEAR
        # `as_of` 계약 ⑵ — 실제로 쓴 값을 meta에도 싣는다(`§2.8`과 같다)
        assert body["meta"]["as_of"] == data["as_of"]

        # 키 집합은 종류와 무관하게 같다 — 키 유무로 종류를 추측하게 하지 않는다
        for item in data["items"]:
            assert set(item) == ITEM_KEYS
            assert item["level"] in {"RISK", "CHECK"}
            assert item["kind"] in KIND_ORDER

        counts = data["counts"]
        assert counts["total"] == len(data["items"])
        assert counts["risk"] + counts["check"] == counts["total"]

        out_of_range = client.get(f"{API_V1_PREFIX}/fleet/notifications?regulation_year=1999")
        assert out_of_range.status_code == 422


def test_order_is_level_then_kind(migrated_db, app_fresh_engine):
    """순서는 단계(RISK → CHECK) → 종류다. 화면은 다시 정렬하지 않는다."""
    with TestClient(app, base_url=_BASE) as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        items = _get(client, f"/fleet/notifications?regulation_year={YEAR}&as_of={AS_OF}")["data"][
            "items"
        ]

        ranks = [KIND_ORDER.index(item["kind"]) for item in items]
        assert ranks == sorted(ranks)
        levels = [item["level"] for item in items]
        assert levels == sorted(levels, key=lambda level: 0 if level == "RISK" else 1)

        soon = [item["days"] for item in items if item["kind"] == "D_ENTRY_SOON"]
        assert soon == sorted(soon)


def test_counts_match_the_two_sources(migrated_db, app_fresh_engine):
    """**같은 판정의 모음이다** — 선대 요약 · 데이터 점검과 수가 같다."""
    with TestClient(app, base_url=_BASE) as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        items = _get(client, f"/fleet/notifications?regulation_year={YEAR}&as_of={AS_OF}")["data"][
            "items"
        ]
        summary = _get(client, f"/fleet/summary?regulation_year={YEAR}&as_of={AS_OF}&limit=100")[
            "data"
        ]
        quality = _get(client, f"/fleet/data-quality?regulation_year={YEAR}")["data"]

        def kind(name: str) -> list[dict]:
            return [item for item in items if item["kind"] == name]

        # 시정조치계획 대상 — `actions[]` 한 행마다
        assert sorted((i["vessel_id"], i["reason"]) for i in kind("CORRECTIVE_ACTION")) == sorted(
            (a["vessel_id"], a["reason"]) for a in summary["actions"]
        )

        # D등급 진입 임박 — `days_to_d`가 있는 선박(올해 안에 진입). 단 CII 적용 대상이
        # 아닌 선박(GT를 알고 5,000 미만)은 뺀다 — 위험 선박 정의와 같다(`#2132`)
        soon = [
            v
            for v in summary["vessels"]
            if v["days_to_d"] is not None
            and not (v["gross_tonnage"] is not None and v["gross_tonnage"] < 5000)
        ]
        assert sorted((i["vessel_id"], i["days"]) for i in kind("D_ENTRY_SOON")) == sorted(
            (v["vessel_id"], v["days_to_d"]) for v in soon
        )

        # 실적 확정 전 항차 — `UNCONFIRMED` 항차마다 한 행
        unconfirmed = {
            issue["voyage_id"]
            for issue in quality["issues"]
            if issue["severity"] == "UNCONFIRMED" and issue["voyage_id"] is not None
        }
        assert {i["voyage_id"] for i in kind("UNCONFIRMED_VOYAGE")} == unconfirmed
        assert len(kind("UNCONFIRMED_VOYAGE")) == len(unconfirmed)

        # 실측이 아닌 값 — 선박마다 한 행, `count`는 그 선박의 해당 행 수
        estimated: dict[str, int] = {}
        for issue in quality["issues"]:
            if issue["severity"] in {"SUBSTITUTED", "UNAVAILABLE", "ANOMALY"}:
                estimated[issue["vessel_id"]] = estimated.get(issue["vessel_id"], 0) + 1
        assert {i["vessel_id"]: i["count"] for i in kind("ESTIMATED_VALUES")} == estimated
