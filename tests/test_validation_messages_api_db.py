"""실제 엔드포인트의 422가 한국어인가 (``API_SPEC §1.3.2`` 언어 규정 · #900).

``tests/test_validation_messages.py``가 문장 틀과 라벨 표를 본다면, 여기서는 **실제 앱을
거친 응답**을 본다 — 발견 경로(`#877`)였던 가입·로그인과, 인증 뒤의 선박·항차·목록 조회.
각 응답에서 ``error.message``·``details[].message``·``details[].field_label``이 **전부
한국어**인지 단언한다(이슈의 완료 기준 문장 그대로).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.db.demo_seed import VESSEL_ID_BULK

_HANGUL = re.compile(r"[가-힣]")


@pytest.fixture
def anon(migrated_db, app_fresh_engine):
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url="https://testserver") as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def _csrf(client: TestClient) -> dict[str, str]:
    """상태 변경 요청의 CSRF 헤더 — 쿠키 원문을 헤더로(``test_audit_actions_db.py``와 같다)."""
    return {"X-CSRF-Token": client.cookies["csrf"]}


def _korean_422(resp) -> dict[str, tuple[str, str]]:
    """422를 확인하고 ``{field: (field_label, message)}``를 돌려준다. 한국어가 아니면 실패."""
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    texts = [error["message"]]
    for detail in error["details"]:
        texts += [detail["message"], detail["field_label"]]
    leaked = [t for t in texts if not _HANGUL.search(t)]
    assert not leaked, f"한국어가 아닌 문구: {leaked}"
    return {d["field"]: (d["field_label"], d["message"]) for d in error["details"]}


def test_signup_reported_in_the_issue(anon):
    """이슈 본문의 실측 세 건 — 길이 초과 · 형식 · 필드 라벨."""
    resp = anon.post(
        f"{API_V1_PREFIX}/auth/signup",
        json={"email": "not-an-email", "password": "x" * 12, "display_name": "가" * 200},
    )
    details = _korean_422(resp)
    assert details["display_name"] == ("표시 이름", "표시 이름은 100자 이하여야 합니다.")
    assert details["email"][0] == "이메일"


def test_login_missing_fields(anon):
    details = _korean_422(anon.post(f"{API_V1_PREFIX}/auth/login", json={}))
    assert details["email"] == ("이메일", "이메일을 입력하세요.")
    assert details["password"] == ("비밀번호", "비밀번호를 입력하세요.")


def test_vessel_registration(client):
    resp = client.post(
        f"{API_V1_PREFIX}/vessels",
        json={"imo_number": "1234567", "ship_type": "BULK_CARRIER", "gross_tonnage": "abc"},
        headers=_csrf(client),
    )
    details = _korean_422(resp)
    assert details["name"] == ("선명", "선명을 입력하세요.")
    assert details["gross_tonnage"][0] == "총톤수(GT)"


def test_nested_voyage_fuel_field(client):
    """배열 원소 안의 필드도 라벨을 찾는다 — ``fuel_uses[0].planned_fuel_ton``."""
    resp = client.post(
        f"{API_V1_PREFIX}/vessels/{VESSEL_ID_BULK}/voyages",
        json={
            "planned_distance_nm": "abc",
            "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "x"}],
        },
        headers=_csrf(client),
    )
    details = _korean_422(resp)
    assert details["planned_distance_nm"][0] == "계획 거리"
    assert details["fuel_uses[0].planned_fuel_ton"][0] == "계획 연료량"


def test_query_parameter(client):
    details = _korean_422(client.get(f"{API_V1_PREFIX}/vessels", params={"limit": "abc"}))
    assert details["limit"] == ("페이지 크기", "페이지 크기는 정수여야 합니다.")


def test_custom_validator_keeps_its_korean_message(client):
    resp = client.post(
        f"{API_V1_PREFIX}/annual-simulations",
        json={"vessel_id": VESSEL_ID_BULK, "regulation_year": 2026, "random_seed": "abc"},
        headers=_csrf(client),
    )
    details = _korean_422(resp)
    assert details["random_seed"] == ("난수 시드(seed)", "난수 시드(seed)는 정수여야 합니다.")
