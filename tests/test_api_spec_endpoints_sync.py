"""`API_SPEC §12` 엔드포인트 요약표 ↔ 실제 라우트 (#591).

## 왜 필요한가

`#591`이 **손으로** 대조해 어긋남을 찾았고, 어긋남은 **양방향**이었다.

======================================  =====================================
 문서에만 있음 (명세했는데 없다)          `weather` 2종 · `parameters/import`
 코드에만 있음 (만들었는데 안 적었다)     `#506` 계정 관리 3종
======================================  =====================================

뒤엣것이 특히 조용하다 — `§1.2` 본문에는 있는데 `§12` 요약표에만 없어서, **같은
문서가 자기와 어긋난** 상태로 두 판(v1.19 → v1.21)을 지났다. 사람이 51행을 눈으로
훑어 찾을 수 있는 종류가 아니다.

## 「미구현」을 문서에만 적으면 낡는다

`#591`의 판정은 C안(스펙에 남긴다)이다. 그런데 **라우트가 없어** `#556`처럼
docstring에 판정을 남길 자리가 없다. 문서에만 적으면 누군가 구현했을 때 표시가
그대로 남아 「미구현」이라고 거짓말한다.

그래서 표시를 **검사 가능한 주장**으로 바꾼다 — 「미구현이라고 적은 것은 정말
없어야 한다」. 구현되는 날 이 테스트가 깨지고, 표시를 지우게 한다.

## `app.routes`를 보지 않는다

이 FastAPI 판은 `include_router`가 라우터를 감싸서 `app.routes`에 하위 경로가
드러나지 않는다 — `#634`에서 **0개를 검사하고 통과**하는 가드를 만들 뻔했다.
OpenAPI 문서를 읽는다.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `API_SPEC §12` 행 — `| GET | `/api/v1/...` | 기능 | 참조 |`
_ROW = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|([^|]*)\|", re.M)

#: 기능 칸에 이 문구가 있으면 「명세는 있으나 라우트는 없다」는 주장이다.
_UNIMPLEMENTED = "미구현"

_SPEC = Path(__file__).resolve().parents[1] / "API_SPEC.md"


def _normalize(path: str) -> str:
    """경로 파라미터 이름을 지운다.

    요약표는 `{id}`로, 구현은 `{vessel_id}`·`{voyage_id}`로 적는다. 이름까지 맞추라고
    요구하면 **문서를 실제 코드에 종속시키는** 것이라, 이 가드가 잡아야 할 것(경로가
    있는가 없는가)과 무관한 실패가 난다.
    """
    return re.sub(r"\{[^}]*\}", "{}", path)


def _documented() -> dict[tuple[str, str], bool]:
    """`{(method, path): 미구현인가}`."""
    text = _SPEC.read_text(encoding="utf-8")
    section = text.split("## 12. 엔드포인트 요약", 1)[1].split("\n---", 1)[0]
    return {
        (method, _normalize(path)): _UNIMPLEMENTED in feature
        for method, path, feature in _ROW.findall(section)
    }


def _implemented() -> set[tuple[str, str]]:
    from cii_platform.api.main import app

    return {
        (method.upper(), _normalize(path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def test_the_summary_table_is_parsed_at_all() -> None:
    """표를 읽지 못하면 아래 셋이 **「빈 것끼리 같다」로 통과**한다.

    `#591` 시점의 실측이 51행이었다. 형식이 바뀌어 파싱이 깨지면 여기서 멈춘다.
    """
    documented = _documented()

    assert len(documented) >= 50, f"§12 표를 읽지 못했다: {len(documented)}행"
    assert ("GET", "/api/v1/health") in documented
    # 「미구현」 표시가 실제로 읽히는지 — 문구가 바뀌면 판정이 조용히 사라진다.
    assert any(documented.values()), "「미구현」으로 표시된 행을 하나도 읽지 못했다"


def test_routes_are_discovered_at_all() -> None:
    """`app.routes`가 아니라 OpenAPI를 읽는 이유는 모듈 docstring에 있다 (`#634`)."""
    implemented = _implemented()

    assert len(implemented) >= 50, f"라우트를 읽지 못했다: {len(implemented)}개"
    assert ("GET", "/api/v1/health") in implemented


def test_unimplemented_endpoints_really_have_no_route() -> None:
    """「미구현」이라고 적은 것은 **정말 없어야** 한다 (`#591` C안 판정).

    구현되는 날 여기가 깨진다 — 그때 `§9`의 ⏸ 블록과 `§12`의 표시를 함께 지운다.
    """
    documented = _documented()
    implemented = _implemented()

    claimed = {key for key, unimplemented in documented.items() if unimplemented}
    assert claimed, "「미구현」 행이 하나도 없다 — 표시 문구가 바뀌었는지 확인할 것"

    lying = sorted(claimed & implemented)
    assert not lying, (
        "§12가 「미구현」이라고 적었지만 라우트가 있습니다. 표시를 지우세요:\n"
        + "\n".join(f"  {method} {path}" for method, path in lying)
    )


def test_documented_endpoints_exist_unless_marked() -> None:
    """표시 없는 것은 **정말 있어야** 한다 — `#591`이 손으로 찾은 그 상태다."""
    documented = _documented()
    implemented = _implemented()

    missing = sorted(
        key
        for key, unimplemented in documented.items()
        if not unimplemented and key not in implemented
    )
    assert not missing, (
        "§12에 있으나 라우트가 없습니다. 구현하거나 「미구현」으로 표시하세요:\n"
        + "\n".join(f"  {method} {path}" for method, path in missing)
    )


def test_no_route_is_missing_from_the_summary_table() -> None:
    """**반대 방향** — 만들고 적지 않은 것.

    `#506`의 계정 관리 3종이 이렇게 빠졌다. `§1.2` 본문에는 있었기 때문에 아무도
    알아채지 못했다 — **요약표만 낡아 있었다.**
    """
    documented = _documented()
    implemented = _implemented()

    undocumented = sorted(implemented - documented.keys())
    assert not undocumented, (
        "라우트가 있으나 §12 요약표에 없습니다. 표에 등재하세요:\n"
        + "\n".join(f"  {method} {path}" for method, path in undocumented)
    )
