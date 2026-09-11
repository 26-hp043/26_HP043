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
import re
from pathlib import Path
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


# ─── 열 구성 — `API_SPEC §8.1`과 대조 (#753) ──────────────────────────────────
#
# 파일 응답에는 필드 집합이 없다. 내보내기에서 그 자리를 하는 것이 **헤더 행**이다 —
# 받은 쪽(엑셀·재가져오기)은 열 이름과 순서로 값을 읽는다. 열 목록의 정본은
# `API_SPEC §8.1`이고, 서비스 상수(`VOYAGE_COLUMNS` 등)와 **정본 사이를 잇는 검사가 없었다.**
# 상수만 보면 상수를 고칠 때 검사도 함께 따라가 아무것도 잡지 못한다.

_API_SPEC = Path(__file__).resolve().parents[1] / "API_SPEC.md"


def _spec_columns(export_type: str) -> list[str]:
    """`API_SPEC §8.1`의 「`type=…` 컬럼 (N열)」 절에서 열 이름을 순서대로 뽑는다.

    표로 적힌 절(`voyages`)은 둘째 칸만, 목록으로 적힌 절은 첫 목록 줄만 읽는다 —
    설명 문장의 백틱(`§8.2` 등)을 열로 읽지 않기 위해서다. **제목의 N열과 개수를
    대조한다** — 판별이 틀리면 여기서 먼저 실패한다.
    """
    text = _API_SPEC.read_text(encoding="utf-8")
    match = re.search(
        rf"^#### `type={export_type}` 컬럼 \((\d+)열\)\n(.*?)(?=^#{{3,4}} )",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"API_SPEC §8.1에서 type={export_type} 절을 찾지 못했습니다"
    count, body = int(match[1]), match[2]
    lines = body.splitlines()
    cells = [line.split("|")[2] for line in lines if re.match(r"^\| \d", line)]
    if not cells:
        cells = [next(line for line in lines if line.startswith("`"))]
    columns = [name for cell in cells for name in re.findall(r"`([a-z_][a-z0-9_]*)`", cell)]
    assert len(columns) == count, (
        f"type={export_type}: 제목은 {count}열, 읽은 것은 {len(columns)}열"
    )
    return columns


@pytest.mark.parametrize("export_type", ["voyages", "calculations", "simulations"])
def test_내보내기_헤더_행이_정본의_열과_같다(client, export_type):
    """CSV 헤더와 JSON ``columns``가 **`API_SPEC §8.1`의 열 이름·순서와 같다.**

    순서까지 본다 — `voyages`의 앞 일곱 열은 가져오기(`§8.2`)가 같은 순서로 읽는
    **왕복 구간**이라, 순서가 바뀌면 내보낸 파일을 다시 가져올 수 없다.
    """
    expected = _spec_columns(export_type)
    url = f"/api/v1/vessels/{VESSEL_ID_BULK}/export"

    csv_response = client.get(url, params={"type": export_type, "format": "csv"})
    assert csv_response.status_code == 200, csv_response.text
    header = csv_response.content.decode("utf-8-sig").splitlines()[0]
    assert header.split(",") == expected

    json_response = client.get(url, params={"type": export_type, "format": "json"})
    assert json_response.status_code == 200, json_response.text
    assert json_response.json()["data"]["columns"] == expected
