"""리포트·내보내기 **라우트 층**의 HTTP 계약 (``#911``).

**막으려는 것은 계산 오류가 아니라, 사용자가 실제로 지나가는 경로가 검사 밖에 있는 것이다.**

``#871``이 커버리지 계측을 고친 뒤에도 두 파일은 수치가 그대로였다.

.. code-block:: text

    routes/exports.py   65% → 65%    전부 실제 공백
    routes/reports.py   61% → 61%    전부 실제 공백 (format 분기 통째로 미실행)

기존 리포트 검사는 **서비스를 직접 부른다.** 그래서 형식 분기(``pdf``·``csv``·``html``),
``Content-Disposition``, JSON 봉투의 ``row_count``처럼 **라우트에만 있는 것**은 아무도
실행하지 않았다. 내보내기는 ``#890``이 화면에 붙이면서 사용자가 실제로 누르는 버튼이 됐다.

전체 합계 게이트(90%)는 이 구멍을 볼 수 없다 — 5,897문장 중 69문장이 60%대여도 합계는
96%다. 파일별 하한은 별도 정책 판단이라 이 파일은 **두 파일의 공백만** 채운다.

데모 선박 ``VESSEL_ID_BULK``는 올해 완료 항차와 계산 이력을 갖는다.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.demo_seed import VESSEL_ID_BULK

_BASE = "https://testserver"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        assert c.post("/api/v1/auth/dev-login").status_code == 200
        yield c


def _assert_attachment(response, extension: str) -> None:
    """``filename``(ASCII)과 ``filename*``(UTF-8)을 **둘 다** 보낸다 (RFC 6266 §4.3).

    한글 파일명만 보내면 구형 클라이언트가 깨진 이름으로 저장하고, ASCII만 보내면
    받은 파일이 무엇인지 알 수 없다.
    """
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'.{extension}"' in disposition, disposition
    utf8 = disposition.split("filename*=UTF-8''", 1)
    assert len(utf8) == 2, f"filename*가 없습니다: {disposition}"
    assert unquote(utf8[1]).endswith(f".{extension}")


# ─── routes/reports.py ──────────────────────────────────────────────────────


def test_연간_리포트_html은_첨부가_아니라_화면에_그린다(client):
    """미리보기는 화면에 그린다 — ``Content-Disposition``을 붙이지 않는다."""
    r = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/annual-report", params={"format": "html"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "content-disposition" not in r.headers
    assert "<html" in r.text.lower()


def test_연간_리포트_csv는_첨부로_내려간다(client):
    r = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/annual-report", params={"format": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    _assert_attachment(r, "csv")
    assert r.text.strip(), "CSV 본문이 비었습니다"


def test_연간_리포트_pdf는_첨부로_내려간다(client):
    """CI는 ``libpango``·``fonts-nanum``을 설치한다 — 없는 환경에서는 건너뛴다."""
    from cii_platform.reports import pdf as pdf_module

    if not pdf_module.is_available() or not pdf_module.has_korean_font():
        pytest.skip("PDF 렌더러 또는 한국어 폰트가 없는 환경")
    r = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/annual-report", params={"format": "pdf"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    _assert_attachment(r, "pdf")


def test_리포트_형식이_틀리면_422다(client):
    """지원 형식 밖은 **어떤 형식이 되는지 알려 주는** 422다 — 조용히 PDF로 내려가지 않는다."""
    r = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/annual-report", params={"format": "xml"})
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "format"


def test_항차_리포트_라우트도_같은_형식_분기를_탄다(client):
    """항차 완료 리포트(`API_SPEC §8.3`)는 **확정·완료 항차**가 대상이다."""
    voyages = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/voyages").json()["data"]
    done = next((v for v in voyages if v["status"] in ("COMPLETED", "CONFIRMED")), None)
    assert done is not None, "사전 조건: 데모 선박에 완료 항차가 있어야 한다"

    html = client.get(f"/api/v1/voyages/{done['id']}/report", params={"format": "html"})
    csv = client.get(f"/api/v1/voyages/{done['id']}/report", params={"format": "csv"})
    assert html.status_code == 200, html.text
    assert "content-disposition" not in html.headers
    assert csv.status_code == 200, csv.text
    _assert_attachment(csv, "csv")


# ─── routes/exports.py ──────────────────────────────────────────────────────


@pytest.mark.parametrize("export_type", ["voyages", "calculations", "simulations"])
def test_내보내기_csv는_type마다_첨부로_내려간다(client, export_type):
    r = client.get(
        f"/api/v1/vessels/{VESSEL_ID_BULK}/export", params={"type": export_type, "format": "csv"}
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    _assert_attachment(r, "csv")
    # 헤더 행은 행이 0건이어도 나간다 — 받은 쪽이 열 구성을 알 수 있다.
    assert r.text.splitlines(), "CSV에 헤더 행조차 없습니다"


@pytest.mark.parametrize("export_type", ["voyages", "calculations", "simulations"])
def test_내보내기_json은_봉투에_행_수를_싣는다(client, export_type):
    """``meta.row_count``가 **실제 행 수와 같다** — 받은 쪽이 잘렸는지 판단할 근거다."""
    r = client.get(
        f"/api/v1/vessels/{VESSEL_ID_BULK}/export", params={"type": export_type, "format": "json"}
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in r.headers
    body = json.loads(r.text)
    assert body["data"]["type"] == export_type
    assert isinstance(body["data"]["columns"], list) and body["data"]["columns"]
    assert body["meta"]["row_count"] == len(body["data"]["rows"])
    assert body["meta"]["request_id"]
    assert body["meta"]["timestamp"]


def test_내보내기_year_필터가_봉투에_그대로_실린다(client):
    r = client.get(
        f"/api/v1/vessels/{VESSEL_ID_BULK}/export",
        params={"type": "voyages", "format": "json", "year": 2025},
    )
    assert r.status_code == 200, r.text
    assert json.loads(r.text)["data"]["year"] == 2025


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"type": "voyages", "format": "xml"}, "format"),
        ({"type": "nope", "format": "csv"}, "type"),
    ],
)
def test_내보내기_잘못된_형식과_종류는_422다(client, params, field):
    r = client.get(f"/api/v1/vessels/{VESSEL_ID_BULK}/export", params=params)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"][0]["field"] == field
