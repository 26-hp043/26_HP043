"""계산 이력 조회 API 계약 테스트 (#56) — **DB 없이 돈다.**

저장소 함수를 monkeypatch로 갈아 끼우고 세션 의존성을 대역으로 바꿔, **라우트 →
서비스 → 직렬화 → JSON** 전 구간을 실제 HTTP 요청으로 통과시킨다.

이 방식으로 잡는 것: 필드명 오타, ``result_summary`` 추출 누락, 커서 형식 오류의
422, ``has_more``·``next_cursor`` 페이지네이션 메타, ``meta`` 누락, 필터 전달 누락.

이 방식으로 못 잡는 것: 실제 keyset 쿼리의 정렬·커서 비교 정합성. 그건 DB가 있는
CI에서 별도 테스트가 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fakes import FAKE_SESSION_TOKEN, FakeSession, install_fake_auth
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.auth.session import SESSION_COOKIE_NAME
from cii_platform.db.repositories.calculation_run import (
    CalcRunCursor,
    decode_cursor,
    encode_cursor,
)
from cii_platform.db.session import get_session

ENDPOINT = "/api/v1/calculations"

#: API_SPEC §1.9 예시의 hash 형식. 형식 자체는 검증하지 않으므로(모든 문자열 허용)
#: 서로 다른 두 값을 구분할 수만 있으면 된다.
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


@dataclass
class FakeCalcRow:
    """``CalculationRun`` 행 대역. 조회 응답 직렬화에 쓰이는 필드만 가진다."""

    id: UUID = field(default_factory=uuid4)
    calculation_type: str = "VOYAGE_ESTIMATE"
    vessel_id: str = field(default_factory=lambda: str(uuid4()))
    voyage_id: str | None = None
    input_hash: str = HASH_A
    parameter_hash: str = HASH_B
    model_version: dict[str, object] = field(
        default_factory=lambda: {"major": 1, "minor": 0, "patch": 0}
    )
    result_json: dict[str, object] = field(
        default_factory=lambda: {
            "attained_cii": "4.982400",
            "estimated_rating": "C",
            "required_cii": "5.045066",
        }
    )
    needs_recalc: bool = False
    created_at: datetime = field(default_factory=lambda: datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> Iterator[TestClient]:
    """조회 저장소를 대역으로 바꾸고 클라이언트를 준다.

    **서비스 모듈이 import한 이름을 바꾼다.** ``services.calculation``은
    ``calc_run_repo`` 모듈 객체를 참조하므로, 그 모듈의 ``list_runs`` 속성을
    갈아 끼운다(``from ... import X`` 형태는 원본 patch로 안 바뀐다).
    """
    from cii_platform.services import calculation as svc

    async def fake_list_runs(
        _session,
        *,
        limit,
        cursor=None,
        input_hash=None,
        parameter_hash=None,
        calculation_type=None,
        vessel_id=None,
    ):
        return []

    monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

    # 인증 배선(#307) 후 main.app은 세션 없이 401 — 대역 세션으로 통과시킨다.
    # GET 조회이므로 CSRF 헤더는 필요 없다.
    install_fake_auth(monkeypatch)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, FAKE_SESSION_TOKEN)
        yield client
    app.dependency_overrides.clear()


# --- 커서 인코딩/디코딩 --------------------------------------------------------------


class TestCursorCodec:
    """API_SPEC §1.9 커서 왕복 — vessel · voyage와 같은 정책."""

    def test_roundtrip(self):
        cursor = CalcRunCursor(
            created_at=datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC),
            calculation_run_id=uuid4(),
        )
        assert decode_cursor(encode_cursor(cursor)) == cursor

    def test_non_utc_timezone(self):
        cursor = CalcRunCursor(
            created_at=datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone(timedelta(hours=9))),
            calculation_run_id=uuid4(),
        )
        assert decode_cursor(encode_cursor(cursor)) == cursor

    @pytest.mark.parametrize(
        "token",
        [
            "",
            "not-base64!!",
            "aGVsbG8=",  # 구분자(\x00)가 없는 유효 base64
            "aGVsbG8A",  # 구분자만 있고 id가 없음
        ],
    )
    def test_broken_cursor_returns_none_not_exception(self, token):
        """깨진 커서는 None — 서비스가 422로 바꾼다(예외를 삼키지 않는다)."""
        assert decode_cursor(token) is None


# --- 조회 계약 -----------------------------------------------------------------------


class TestListCalculations:
    """GET /calculations 응답 계약 (API_SPEC §1.9)."""

    def test_empty_result(self, wired: TestClient):
        resp = wired.get(ENDPOINT)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["next_cursor"] is None
        assert body["meta"]["has_more"] is False
        # §1.3.1 — request_id·timestamp는 meta에서 빠지지 않는다.
        assert set(body["meta"]) == {"next_cursor", "has_more", "request_id", "timestamp"}

    def test_data_fields(self, wired: TestClient, monkeypatch: pytest.MonkeyPatch):
        """§1.9 ``data[]`` 항목 — 필드명과 result_summary 추출."""
        row = FakeCalcRow()
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, **_kwargs):
            return [row]

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        body = wired.get(ENDPOINT).json()
        item = body["data"][0]
        assert item["calculation_run_id"] == str(row.id)
        assert item["calculation_type"] == row.calculation_type
        assert item["vessel_id"] == row.vessel_id
        assert item["voyage_id"] is None
        assert item["input_hash"] == HASH_A
        assert item["parameter_hash"] == HASH_B
        assert item["model_version"] == {"major": 1, "minor": 0, "patch": 0}
        # result_json 전체가 아니라 §1.9가 정의한 요약 키만 노출한다.
        assert item["result_summary"] == {
            "attained_cii": "4.982400",
            "estimated_rating": "C",
        }
        assert "required_cii" not in item["result_summary"]
        assert item["created_at"] == "2026-07-03T12:00:00+00:00"
        assert item["needs_recalc"] is False

    def test_result_summary_missing_keys_omitted(
        self, wired: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        """result_json에 요약 키가 없으면 값이 아니라 키 자체를 생략한다."""
        row = FakeCalcRow(result_json={"required_cii": "5.045066"})
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, **_kwargs):
            return [row]

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        item = wired.get(ENDPOINT).json()["data"][0]
        assert item["result_summary"] == {}

    def test_filters_forwarded(self, wired: TestClient, monkeypatch: pytest.MonkeyPatch):
        """쿼리 파라미터가 저장소로 그대로 전달된다 (AND 결합)."""
        recorded: dict[str, object] = {}
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, **_kwargs):
            recorded.update(**_kwargs)
            return []

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        vessel_id = str(uuid4())
        resp = wired.get(
            ENDPOINT,
            params={
                "input_hash": HASH_A,
                "parameter_hash": HASH_B,
                "type": "VOYAGE_ESTIMATE",
                "vessel_id": vessel_id,
            },
        )
        assert resp.status_code == 200
        assert recorded["input_hash"] == HASH_A
        assert recorded["parameter_hash"] == HASH_B
        assert recorded["calculation_type"] == "VOYAGE_ESTIMATE"
        # FastAPI가 쿼리 파라미터를 UUID 객체로 변환해 서비스로 넘긴다.
        assert str(recorded["vessel_id"]) == vessel_id
        assert recorded["cursor"] is None

    def test_limit_default_and_cap(self, wired: TestClient, monkeypatch: pytest.MonkeyPatch):
        """기본 20 · 최대 100 (vessel · voyage와 동일 정책)."""
        seen: list[int] = []
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, *, limit, **_kwargs):
            seen.append(limit)
            return []

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        wired.get(ENDPOINT)
        wired.get(ENDPOINT, params={"limit": 5})
        wired.get(ENDPOINT, params={"limit": 999})
        assert seen == [20, 5, 100]

    def test_limit_below_one_is_422(self, wired: TestClient, monkeypatch: pytest.MonkeyPatch):
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, *, limit, **_kwargs):
            return []

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        resp = wired.get(ENDPOINT, params={"limit": 0})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"][0]["field"] == "limit"

    def test_broken_cursor_is_422(self, wired: TestClient, monkeypatch: pytest.MonkeyPatch):
        """깨진 커서는 422 — 사용자가 URL을 손댄 경우 500이 나가면 안 된다."""
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, *, limit, cursor=None, **_kwargs):
            return []

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        resp = wired.get(ENDPOINT, params={"cursor": "not-base64!!"})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"][0]["field"] == "cursor"

    def test_has_more_true_and_cursor_returned(
        self, wired: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        """``limit + 1``건 → has_more=True, next_cursor는 마지막 항목을 가리킨다."""
        page_size = 20
        rows = [FakeCalcRow() for _ in range(page_size + 1)]
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, *, limit, **_kwargs):
            return rows

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        body = wired.get(ENDPOINT, params={"limit": page_size}).json()
        assert len(body["data"]) == page_size  # 초과분은 잘라낸다
        assert body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"] is not None

        cursor = decode_cursor(body["meta"]["next_cursor"])
        assert cursor is not None
        assert cursor.created_at == rows[-2].created_at
        assert cursor.calculation_run_id == rows[-2].id

    def test_next_cursor_none_on_exact_page(
        self, wired: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        """정확히 limit개면 has_more=False — 커서를 돌려주면 무한 루프 유혹이 된다."""
        rows = [FakeCalcRow() for _ in range(3)]
        from cii_platform.services import calculation as svc

        async def fake_list_runs(_session, *, limit, **_kwargs):
            return rows

        monkeypatch.setattr(svc.calc_run_repo, "list_runs", fake_list_runs)

        body = wired.get(ENDPOINT, params={"limit": 3}).json()
        assert body["meta"]["has_more"] is False
        assert body["meta"]["next_cursor"] is None
