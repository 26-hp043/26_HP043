"""보존 기간 ↔ `DB_SCHEMA §4.3` 대조 (`#1347`).

## 왜 필요한가

`scripts/purge_expired.py`는 **지우는 것**이고, 지운 것은 되돌릴 수 없다. 그 기간이
정본보다 **짧으면** 보존 약속을 깨고, **길면** 「30일 뒤 지워진다」가 거짓이 된다.
둘 다 조용히 어긋난다 — 스크립트는 정상 종료하고 표만 줄어든다.

`#1347`에서 이 표는 **아무도 읽지 않는 상태**였다: `§4.3`이 *「`weather_snapshot`
30일(TTL 만료 후 삭제)」*이라 적는데 **지우는 경로 자체가 없었다.**
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_SCHEMA = ROOT / "DB_SCHEMA.md"


def _purge_module():
    spec = importlib.util.spec_from_file_location(
        "purge_expired", ROOT / "scripts" / "purge_expired.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["purge_expired"] = module
    spec.loader.exec_module(module)
    return module


def _retention_row(table: str) -> str:
    text = DB_SCHEMA.read_text(encoding="utf-8")
    start = text.index("### 4.3 백업 및 보존")
    section = text[start : text.index("\n---", start)]
    for line in section.splitlines():
        if line.startswith(f"| `{table}`"):
            return line
    raise AssertionError(f"§4.3에 `{table}` 행이 없다")


def test_기상_스냅샷_보존일이_정본과_같다() -> None:
    module = _purge_module()
    documented = re.search(r"\|\s*(\d+)일", _retention_row("weather_snapshot"))

    assert documented, "§4.3의 weather_snapshot 행에서 일수를 읽지 못했다"
    assert int(documented.group(1)) == module.WEATHER_RETENTION_DAYS


def test_정본이_지운다고_적은_표는_스크립트가_다룬다() -> None:
    """**「삭제」라고 적힌 행에는 지우는 경로가 있어야 한다** (`#1347`).

    이 검사가 없던 동안 `weather_snapshot` 행이 *「TTL 만료 후 삭제」*라고 적으면서
    **어디서도 지워지지 않았다.** 보존 표를 운영 계약으로 읽으면 그 문장이 거짓이다.
    """
    module = _purge_module()
    text = DB_SCHEMA.read_text(encoding="utf-8")
    start = text.index("### 4.3 백업 및 보존")
    section = text[start : text.index("\n---", start)]

    claims_deletion = [
        match.group(1)
        for line in section.splitlines()
        if "삭제" in line and (match := re.match(r"\| `(\w+)`", line))
    ]

    assert claims_deletion, "§4.3에서 삭제를 약속하는 행을 하나도 찾지 못했다"
    assert set(claims_deletion) <= set(module._SQL), (
        f"정본은 지운다고 적는데 스크립트에 없다: {set(claims_deletion) - set(module._SQL)}"
    )
