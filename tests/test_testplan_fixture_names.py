"""`TEST_PLAN §1.6` 표의 이름이 `tests/conftest.py`에 실재한다 (`#1583` · 결정요청 v3 `E-9`).

종전 `§1.6`은 저장소에 없는 `db_session`·`httpx_client`를 정본으로 적고 있었다. 검사는 초록인데
문서가 어긋나는 형태라 **아무도 알아채지 못했다** — 새로 검사를 쓰는 사람이 그 이름을 찾아야
처음 드러난다. 사본은 가드가 지킨다(`#830`의 `§14.2` 합계와 같은 해법).
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _section_names() -> list[str]:
    text = (_ROOT / "TEST_PLAN.md").read_text(encoding="utf-8")
    start = text.index("### 1.6 ")
    stop = text.index("### 1.7 ", start)
    return re.findall(r"^\| `([A-Za-z_][A-Za-z0-9_]*)` \|", text[start:stop], re.M)


def test_section_lists_names():
    """표가 비면 아래 검사가 헛돈다 — 이름이 하나 이상 잡혀야 한다."""
    assert len(_section_names()) >= 4


def test_every_name_is_defined_in_conftest():
    source = (_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    defined = set(re.findall(r"^(?:async )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source, re.M))
    missing = [name for name in _section_names() if name not in defined]
    assert missing == [], f"TEST_PLAN §1.6에 적혔으나 conftest.py에 없는 이름: {missing}"
