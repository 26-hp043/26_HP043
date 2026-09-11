"""샘플 선박 목록 (#982 · `API_SPEC §2.15` · `PRD §5.1` 「샘플 선박 선택」).

잠그는 것:

* **값의 출처가 데모 시드 한 곳이다** — 샘플과 시드의 같은 배가 다른 제원을 가지면
  「샘플로 등록한 배」와 「데모의 같은 이름 배」가 다른 계산을 낸다
* **합성 샘플만** 싣는다 — 실존 선박(IMO가 실제 값인 시드 2척)은 샘플이 아니다
* 샘플이 싣는 필드 = 등록 요청 필드 − 신원(IMO·선명). 등록 스키마가 필드를 늘리면 여기서 드러난다
* 샘플은 **바로 계산되는 제원**이다 — 기준속도·기준 일일 연료가 비지 않는다
* ``/vessels/samples``가 ``/vessels/{vessel_id}``에 먹히지 않는다(등록 순서)
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.schemas.vessel import VesselCreateRequest
from cii_platform.db.demo_seed import SEED_VESSEL_GT_AXIS, SEED_VESSEL_WATCH, SEED_VESSELS
from cii_platform.services.sample_vessels import SAMPLE_SPEC_FIELDS, list_sample_vessels

_SEED_BY_NAME = {
    row["name"]: row for row in (*SEED_VESSELS, *SEED_VESSEL_WATCH, *SEED_VESSEL_GT_AXIS)
}


def test_every_sample_is_a_seed_vessel_with_the_same_specs():
    samples = list_sample_vessels()
    assert len(samples) >= 3  # `PRD §22` — 샘플 선박 3개 이상
    for sample in samples:
        seed = _SEED_BY_NAME[sample["label"]]
        for field in SAMPLE_SPEC_FIELDS:
            want = seed[field]
            got = sample[field]
            if want is None:
                assert got is None, field
            elif isinstance(want, Decimal):
                assert Decimal(str(got)) == want, (sample["sample_id"], field)
            else:
                assert got == want, (sample["sample_id"], field)


def test_only_synthetic_vessels_are_samples():
    """합성 IMO(``00000``으로 시작)만 샘플이다 — 실존 선박을 제품이 「샘플」로 권하지 않는다."""
    for sample in list_sample_vessels():
        assert str(_SEED_BY_NAME[sample["label"]]["imo_number"]).startswith("00000")


def test_sample_fields_are_the_create_fields_without_identity():
    """등록 요청 필드 − {IMO, 선명}. 등록 스키마가 필드를 늘리면 여기서 드러난다."""
    create_fields = set(VesselCreateRequest.model_fields)
    assert set(SAMPLE_SPEC_FIELDS) == create_fields - {"imo_number", "name"}
    for sample in list_sample_vessels():
        assert "imo_number" not in sample and "name" not in sample


def test_samples_are_immediately_computable():
    """샘플의 목적은 바로 계산되는 제원이다 — 기준속도·기준 일일 연료·용량이 비지 않는다."""
    for sample in list_sample_vessels():
        assert sample["reference_speed_kn"] and sample["reference_daily_foc_ton"]
        assert sample["deadweight"] or sample["gross_tonnage"]


def test_sample_ids_are_unique_slugs_not_vessel_ids():
    ids = [s["sample_id"] for s in list_sample_vessels()]
    assert len(ids) == len(set(ids))
    for sample_id in ids:
        assert "-" in sample_id and len(sample_id) < 36  # UUID(36자)가 아니다


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url="https://testserver") as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def test_route_is_not_swallowed_by_the_vessel_id_route(client):
    """``/vessels/{vessel_id}``보다 뒤에 등록하면 ``samples``가 UUID 검증에 걸려 422가 된다."""
    resp = client.get(f"{API_V1_PREFIX}/vessels/samples")
    assert resp.status_code == 200, resp.text
    assert [s["sample_id"] for s in resp.json()["data"]] == [
        s["sample_id"] for s in list_sample_vessels()
    ]
