"""표에 없는 규제연도의 안내 문구는 한 함수가 만든다 (`#2478` · `PRD §9.1` VAL-005).

정본은 「`해당 연도의 규정 파라미터가 없습니다.` (+ 호출부가 `(기준연도 {년})`을
덧붙인다)」로 꼴을 정했다. 종전에는 여섯 자리가 각자 f-string으로 조립했고, 항차
생성·수정 한 곳만 「…없습니다: 2031」 꼴이었다. 문구를 한 함수
(``services/calc_errors.regulation_year_missing``)로 모으고, **다시 각자 조립하는 자리가
생기지 않는지** 소스를 읽어 본다 — HTTP 검사는 경로 하나만 보므로 새 자리를 놓친다.
"""

from __future__ import annotations

from pathlib import Path

from cii_platform.errors import ParameterError
from cii_platform.services.calc_errors import REGULATION_YEAR_MISSING, regulation_year_missing

_SRC = Path(__file__).resolve().parents[1] / "src" / "cii_platform"


def test_message_has_the_canonical_shape() -> None:
    # 정본 문구 (PRD §9.1 VAL-005) — 바꾸려면 PRD 개정이 먼저다.
    error = regulation_year_missing(2031)
    assert isinstance(error, ParameterError)
    assert error.message == "해당 연도의 규정 파라미터가 없습니다. (기준연도 2031)"


def test_no_other_place_assembles_the_message() -> None:
    """문구 원문은 ``calc_errors.py`` 한 곳에만 있다.

    챗봇 도구의 「그 조건에 필요한 규정 파라미터가 없습니다.」는 다른 문장이다 — 도구
    실패를 모델에 넘기는 문구라 연도를 싣지 않는다(``chat_tools.py``).
    """
    holders = sorted(
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        if REGULATION_YEAR_MISSING in path.read_text(encoding="utf-8")
    )
    assert holders == ["services/calc_errors.py"], holders
