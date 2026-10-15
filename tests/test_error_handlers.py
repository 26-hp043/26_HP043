"""오류 처리 계약 테스트 (#100, #183).

이 이슈가 확정하는 "계약"을 CI가 지켜주도록 고정한다: base 예외 `AppError`의
HTTP status 매핑(TECH_SPEC §12.1), 오류 응답 포맷(API_SPEC §1.3.2), 그리고
`register_exception_handlers`로 등록된 핸들러의 end-to-end 동작. #183은
프레임워크 404·405와 명시적 `HTTPException`의 변환을 더한다.

DB에 의존하지 않는다(conftest의 `migrated_db`/`conn` 픽스처를 요청하지 않음).

케이스: AT-ERR-003 (`TEST_PLAN §14.5`)
"""

import re

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import (
    register_exception_handlers,
    to_error_response,
)
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.errors import DEFAULT_HTTP_STATUS, AppError


def test_http_status_mapping_from_tech_spec_12_1() -> None:
    # TECH_SPEC §12.1 / API_SPEC §1.4 매핑값과 일치해야 한다.
    assert AppError("VALIDATION_ERROR", "x").http_status == 422
    assert AppError("PARAMETER_ERROR", "x").http_status == 409
    assert AppError("REPRODUCIBILITY_ERROR", "x").http_status == 500


def test_unknown_code_falls_back_to_default_status() -> None:
    # 매핑에 없는 코드는 DEFAULT_HTTP_STATUS(500)로 떨어진다.
    assert AppError("NO_SUCH_CODE", "x").http_status == DEFAULT_HTTP_STATUS
    assert DEFAULT_HTTP_STATUS == 500


def test_to_error_response_matches_api_spec_1_3_2() -> None:
    # API_SPEC §1.3.2: {"error": {"code","message","details"?}, "meta": {...}}
    body = to_error_response(
        "VALIDATION_ERROR",
        "항해거리는 0보다 커야 합니다.",
        details=[{"field": "distance_nm", "field_label": "항해거리"}],
        request_id="req-1",
        timestamp="2026-07-18T00:00:00Z",
    )
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "항해거리는 0보다 커야 합니다."
    assert body["error"]["details"] == [{"field": "distance_nm", "field_label": "항해거리"}]
    assert body["meta"] == {"request_id": "req-1", "timestamp": "2026-07-18T00:00:00Z"}


def test_to_error_response_omits_details_when_none() -> None:
    body = to_error_response("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")
    assert "details" not in body["error"]


def test_to_error_response_omits_none_meta_keys() -> None:
    # API_SPEC §1.3.2는 meta 값을 문자열로 전제 → 값 없는 키는 null 대신 생략.
    body = to_error_response("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")
    assert body["meta"] == {}


def test_registered_handler_converts_app_error_end_to_end() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise AppError("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 409
    payload = resp.json()
    assert payload["error"]["code"] == "PARAMETER_ERROR"
    assert payload["error"]["message"] == "해당 연도의 규정 파라미터가 없습니다."
    assert "details" not in payload["error"]
    # timestamp는 미들웨어 미주입 시에도 핸들러가 UTC ISO8601로 채운다.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["meta"]["timestamp"])
    # request_id는 미들웨어(#49) 도입 전이므로 null 대신 생략된다.
    assert "request_id" not in payload["meta"]


# --- #183: HTTPException → §1.3.2 변환 -------------------------------------------------


#: #183 테스트 전용 앱. main.py를 오염시키지 않고 프레임워크 404·405를 실제로
#: 만들어내기 위해 라우트 1개(GET 전용)만 둔다 — 405가 나오려면 "경로는 존재하나
#: 메서드가 다른" 요청이 필요하다(#183 이슈의 시뮬레이션 방식).
def _http_exception_app() -> FastAPI:
    router = APIRouter()

    @router.get("/only-get")
    async def only_get() -> dict[str, str]:
        return {"ok": "1"}

    @router.get("/boom-422")
    async def boom_422() -> dict[str, str]:
        raise HTTPException(status_code=422, detail="bad")

    @router.get("/boom-409")
    async def boom_409() -> dict[str, str]:
        raise HTTPException(status_code=409, detail="충돌")

    @router.get("/boom-405")
    async def boom_405() -> dict[str, str]:
        raise HTTPException(status_code=405, detail="no")

    @router.get("/boom-400")
    async def boom_400() -> dict[str, str]:
        raise HTTPException(status_code=400, detail="x")

    # PR #223 Copilot 리뷰: 미등록(415)·비표준(499) status fallback 회귀 고정.
    @router.get("/boom-415")
    async def boom_415() -> dict[str, str]:
        raise HTTPException(status_code=415, detail="unsupported")

    @router.get("/boom-499")
    async def boom_499() -> dict[str, str]:
        raise HTTPException(status_code=499, detail="weird")

    # 비-문자열 detail: str() 시 Python repr이 노출되는 것을 막는 계약 (#183).
    @router.get("/boom-dict")
    async def boom_dict() -> dict[str, str]:
        raise HTTPException(status_code=400, detail={"field": "email"})

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    register_exception_handlers(app)
    return app


def test_framework_404_uses_standard_message_and_meta() -> None:
    """⑴ 경로 404 → NOT_FOUND + 표준 문구 + request_id/timestamp (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/no-such-path")
    assert resp.status_code == 404
    payload = resp.json()
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "요청한 경로를 찾을 수 없습니다."
    assert "request_id" in payload["meta"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["meta"]["timestamp"])


def test_framework_405_preserves_allow_header() -> None:
    """⑵ 프레임워크 405 → METHOD_NOT_ALLOWED + Allow 헤더 보존 (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.post("/only-get")
    assert resp.status_code == 405
    assert "get" in resp.headers["allow"].lower()
    payload = resp.json()
    assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert payload["error"]["message"] == "허용되지 않은 HTTP 메서드입니다."


def test_explicit_409_http_exception_falls_back_to_http_error() -> None:
    """HTTPException(409)는 표에 없어 HTTP_ERROR로 나간다 — status 보존 (#2100).

    409는 코드가 셋(PARAMETER_ERROR·MODEL_VERSION_MISMATCH·CONFLICT)이라 status만으로
    고를 수 없다. 셋은 `AppError`로만 나간다.
    """
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-409")
    assert resp.status_code == 409
    payload = resp.json()
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["message"] == "충돌"


def test_explicit_422_uses_http_error_code_and_preserves_detail() -> None:
    """⑶ HTTPException(422, 'bad') → HTTP_ERROR + 'bad' (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-422")
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["message"] == "bad"
    assert "request_id" in payload["meta"]


def test_explicit_405_maps_to_method_not_allowed_and_preserves_detail() -> None:
    """⑷ HTTPException(405, 'no') → METHOD_NOT_ALLOWED + 'no' (#183, #182)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-405")
    assert resp.status_code == 405
    payload = resp.json()
    assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert payload["error"]["message"] == "no"


def test_explicit_400_maps_to_bad_request_and_preserves_detail() -> None:
    """⑸ HTTPException(400, 'x') → BAD_REQUEST + 'x' (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-400")
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["error"]["code"] == "BAD_REQUEST"
    assert payload["error"]["message"] == "x"


def test_normal_response_unaffected_by_http_exception_handler() -> None:
    """⑹ 정상 200 응답은 핸들러 등록 전과 동일하다 (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/only-get")
    assert resp.status_code == 200
    assert resp.json() == {"ok": "1"}


# PR #223 Copilot 리뷰 반영 — 미등록(415)·비표준(499) status fallback 회귀 (#183).


def test_unmapped_415_status_falls_back_to_http_error_and_preserves_status() -> None:
    """⑺ 미등록 status 415 → HTTP_ERROR + status 보존 + 범용 문구 (#183)."""
    resp = TestClient(_http_exception_app()).get("/boom-415")
    assert resp.status_code == 415
    payload = resp.json()
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["message"] == "unsupported"


def test_nonstandard_499_status_falls_back_to_http_error_and_preserves_status() -> None:
    """⑻ 비표준 status 499 → HTTP_ERROR + status 보존 (#183, _status_phrase 빈문자열 경로)."""
    resp = TestClient(_http_exception_app()).get("/boom-499")
    assert resp.status_code == 499
    payload = resp.json()
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["message"] == "weird"


def test_non_string_detail_falls_back_to_generic_message() -> None:
    """⑼ dict detail → 범용 문구로 fallback, Python repr이 message에 노출되지 않는다 (#183)."""
    resp = TestClient(_http_exception_app()).get("/boom-dict")
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["error"]["code"] == "BAD_REQUEST"
    assert payload["error"]["message"] == "요청을 처리할 수 없습니다."
    assert "email" not in payload["error"]["message"]


# --- #117: 갭 보강 — details 3키 구조 · AppError 서브클래스 캐치 -----------------------


def test_details_covers_full_api_spec_1_3_2_three_key_schema() -> None:
    """⑽ §1.3.2 details의 3키(field·field_label·message) 전체 구조 (#117 갭 1 · #2100).

    `rule`은 예시에서 뺐다 — 구현이 싣지 않는다(#2100).
    기존 테스트는 field 1키만 확인했다 — field_label·message 누락은
    실제 응답과의 불일치를 못 잡는다.
    """
    body = to_error_response(
        "VALIDATION_ERROR",
        "항해거리는 0보다 커야 합니다.",
        details=[
            {
                "field": "distance_nm",
                "field_label": "항해거리",
                "message": "항해거리는 0보다 커야 합니다.",
            }
        ],
        request_id="req-4k",
        timestamp="2026-07-18T00:00:00Z",
    )
    entry = body["error"]["details"][0]
    assert set(entry) == {"field", "field_label", "message"}
    assert entry["field_label"] == "항해거리"
    assert entry["message"] == "항해거리는 0보다 커야 합니다."


def test_three_key_details_survive_end_to_end() -> None:
    """⑾ 3키 details가 핸들러를 거쳐 응답 본문에 그대로 나간다 (#117 갭 1)."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-details")
    async def boom_details() -> dict[str, str]:
        raise AppError(
            "VALIDATION_ERROR",
            "항해거리는 0보다 커야 합니다.",
            details=[
                {
                    "field": "distance_nm",
                    "field_label": "항해거리",
                    "message": "항해거리는 0보다 커야 합니다.",
                }
            ],
        )

    payload = TestClient(app).get("/boom-details").json()
    assert payload["error"]["details"] == [
        {
            "field": "distance_nm",
            "field_label": "항해거리",
            "message": "항해거리는 0보다 커야 합니다.",
        }
    ]


def test_validation_error_auto_details_keys() -> None:
    """⑿ ValidationError 자동 details — field·field_label·message 키 (#117 갭 1).

    ``rule``은 키가 아니다 — §1.3.2 예시에서 뺐다(#2100). AppError details로 넘긴 키는
    그대로 통과한다(⑩ 참조).
    """
    from cii_platform.errors import ValidationError

    exc = ValidationError(
        "항해거리는 0보다 커야 합니다.", field="distance_nm", field_label="항해거리"
    )
    assert exc.details is not None
    assert set(exc.details[0]) == {"field", "field_label", "message"}
    assert exc.details[0]["field_label"] == "항해거리"


def test_custom_app_error_subclass_is_caught_by_base_handler() -> None:
    """⒀ 테스트에서 정의한 서브클래스도 base 핸들러가 캐치한다 (#117 갭 2).

    Starlette은 등록된 핸들러 중 예외 MRO에서 가장 가까운 것을 고른다 —
    AppError 핸들러가 서브클래스를 가로채는지 증명한다.
    """

    class SeasonalWindShiftError(AppError):
        """테스트 전용 서브클래스 — 실제 도메인에 추가하는 게 아니다."""

        def __init__(self) -> None:
            super().__init__("WEATHER_FETCH_ERROR", "계절풍 급변으로 기상 모델이 무효화됐습니다.")

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/sub")
    async def sub() -> dict[str, str]:
        raise SeasonalWindShiftError()

    resp = TestClient(app).get("/sub")
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"]["code"] == "WEATHER_FETCH_ERROR"
    assert payload["error"]["message"] == "계절풍 급변으로 기상 모델이 무효화됐습니다."


def test_schema_validation_label_follows_route_for_not_underway_distance() -> None:
    """정박 구간 경로의 ``distance_nm``은 스키마 검증에서도 「이동 거리」다 (#2467).

    서비스가 던지는 오류는 이미 「이동 거리」였는데(#2101) 스키마 검증 경로만 「항해거리」로
    불렀다 — 같은 칸의 오류가 경로에 따라 두 이름으로 나갔다. 다른 자원의 같은 필드명은
    종전 라벨을 그대로 쓴다.
    """
    from pydantic import BaseModel, Field

    from cii_platform.validation.field_labels import field_label

    class Body(BaseModel):
        distance_nm: float = Field(le=10)

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.post("/vessels/{vessel_id}/not-underway-periods")
    async def create_period(vessel_id: str, body: Body) -> dict[str, str]:
        return {}

    @app.patch("/not-underway-periods/{period_id}")
    async def update_period(period_id: str, body: Body) -> dict[str, str]:
        return {}

    @app.post("/voyage-cii/estimate")
    async def estimate(body: Body) -> dict[str, str]:
        return {}

    client = TestClient(app)
    scoped = field_label("not_underway.distance_nm")
    plain = field_label("distance_nm")
    assert scoped != plain

    for method, url in (
        ("post", "/vessels/v1/not-underway-periods"),
        ("patch", "/not-underway-periods/p1"),
    ):
        detail = getattr(client, method)(url, json={"distance_nm": 11}).json()["error"]["details"][
            0
        ]
        assert detail["field"] == "distance_nm"
        assert detail["field_label"] == scoped
        assert str(detail["message"]).startswith(scoped)

    other = client.post("/voyage-cii/estimate", json={"distance_nm": 11}).json()["error"][
        "details"
    ][0]
    assert other["field_label"] == plain
    assert str(other["message"]).startswith(plain)


def test_schema_validation_label_follows_route_for_voyage_year_and_not_underway_fuel() -> None:
    """같은 칸이 스키마 검증·서비스·화면에서 같은 이름으로 불린다 (#2469).

    항차의 ``regulation_year``는 화면이 「기준연도」로 부르고(서비스 오류도 그렇다), 정박 구간의
    ``fuel_uses[].fuel_ton``은 화면이 「연료량」으로 부른다. 스키마 검증 경로만 「규제연도」·
    「연료 사용량」이었다. 다른 자원의 같은 필드명은 종전 라벨을 그대로 쓴다.
    """
    from pydantic import BaseModel, Field

    from cii_platform.validation.field_labels import field_label

    class Fuel(BaseModel):
        fuel_ton: float = Field(le=10)

    class Body(BaseModel):
        regulation_year: int = Field(le=2050)
        fuel_uses: list[Fuel]

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.post("/vessels/{vessel_id}/voyages")
    async def create_voyage(vessel_id: str, body: Body) -> dict[str, str]:
        return {}

    @app.patch("/voyages/{voyage_id}")
    async def update_voyage(voyage_id: str, body: Body) -> dict[str, str]:
        return {}

    @app.post("/vessels/{vessel_id}/not-underway-periods")
    async def create_period(vessel_id: str, body: Body) -> dict[str, str]:
        return {}

    @app.post("/voyage-cii/estimate")
    async def estimate(body: Body) -> dict[str, str]:
        return {}

    client = TestClient(app)
    payload = {"regulation_year": 2051, "fuel_uses": [{"fuel_ton": 11}, {"fuel_ton": 12}]}

    def labels(url: str) -> dict[str, str]:
        details = client.post(url, json=payload).json()["error"]["details"]
        for detail in details:
            assert str(detail["message"]).startswith(str(detail["field_label"]))
        return {str(d["field"]): str(d["field_label"]) for d in details}

    voyage_year = field_label("voyage.regulation_year")
    assert voyage_year != field_label("regulation_year")
    for url in ("/vessels/v1/voyages",):
        assert labels(url)["regulation_year"] == voyage_year
    patched = client.patch("/voyages/x1", json=payload).json()["error"]["details"][0]
    assert patched["field_label"] == voyage_year

    period = labels("/vessels/v1/not-underway-periods")
    fuel = field_label("not_underway.fuel_uses[].fuel_ton")
    assert fuel != field_label("fuel_uses[].fuel_ton")
    # 인덱스가 달라도(0번째·1번째) 같은 라벨이다. 정박 구간의 연도는 종전 「규제연도」다.
    assert period["fuel_uses[0].fuel_ton"] == fuel
    assert period["fuel_uses[1].fuel_ton"] == fuel
    assert period["regulation_year"] == field_label("regulation_year")

    other = labels("/voyage-cii/estimate")
    assert other["regulation_year"] == field_label("regulation_year")
    assert other["fuel_uses[0].fuel_ton"] == field_label("fuel_uses[].fuel_ton")


def test_attribution_message_uses_the_screen_name_of_each_resource() -> None:
    """귀속 연도 문구의 칸 이름은 호출하는 쪽이 정한다 (#2469).

    항차는 「기준연도」, 정박 구간은 「규제연도」다.

    문장 틀과 연도 나열은 두 자원이 같다(`#2133`). 이름만 달라야 한다.
    """
    from cii_platform.services.voyage import attribution_message

    voyage = attribution_message([2026, 2027], subject="항차가", label="기준연도")
    period = attribution_message([2026, 2027], subject="구간이", label="규제연도")
    assert voyage.startswith("기준연도")
    assert period.startswith("규제연도")
    assert "2026 또는 2027" in voyage
    assert "2026 또는 2027" in period


def test_framework_body_parse_error_is_korean() -> None:
    """`#2517` — 깨진 multipart를 FastAPI가 400 「There was an error parsing the body」로 끝낸다.

    문자열 detail이라 「라우트가 넣은 문구」로 보존돼 영어 그대로 나갔다. 실제 업로드 라우트와
    같은 ``UploadFile`` 파라미터에 깨진 본문을 보내 프레임워크 경로 그대로 확인한다.
    """
    from fastapi import File, UploadFile

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict[str, str]:  # noqa: B008
        return {"name": file.filename or ""}

    register_exception_handlers(app)
    client = TestClient(app)
    broken = (
        # FastAPI — 아주 긴 파일명(하니스 재현 입력)
        {"files": {"file": ("a" * 5000 + ".csv", b"x")}},
        # Starlette ``MultiPartException`` — 경계(boundary) 없음
        {"content": b"x", "headers": {"Content-Type": "multipart/form-data"}},
    )
    for kwargs in broken:
        resp = client.post("/upload", **kwargs)
        assert resp.status_code == 400, resp.text
        payload = resp.json()
        assert payload["error"]["code"] == "BAD_REQUEST"
        message = payload["error"]["message"]
        assert re.search(r"[가-힣]", message) and not re.search(r"[A-Za-z]{4,}", message), message
    # 대조군 — 정상 업로드는 그대로다.
    ok = client.post("/upload", files={"file": ("a.csv", b"x")})
    assert ok.status_code == 200 and ok.json() == {"name": "a.csv"}
