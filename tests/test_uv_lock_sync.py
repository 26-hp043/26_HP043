"""``uv.lock``과 ``pyproject.toml``의 동기화 검증 (#399).

## 무엇을 막는가

``uv.lock``이 ``pyproject.toml``보다 **6주 뒤처진 채** 커밋돼 있던 적이 있다.
인증(``#272``~``#279``)이 들어오며 ``pyjwt[crypto]``가 추가됐는데 lock이 따라가지
않았고, ``uv sync``로 만든 환경에서는 ``import jwt``가 실패했다.

**아무것도 그 사실을 알려주지 않았다.** CI의 ``test`` 잡은 ``pip install -e ".[dev]"``를
쓰고 uv를 거치지 않으므로 초록이었다. lock 파일이 커밋돼 있으면서 아무도 검증하지
않는 상태였다 — **있으면 신뢰받고, 신뢰하면 깨진다.**

## 왜 uv를 CI에 설치하지 않는가

``uv lock --check``를 돌리려면 CI에 uv를 새로 들여야 하고, 그러면 **핀이 한 곳 더
생긴다.** ``#478``이 ruff에서 정확히 그 문제를 겪었다 — 버전이 두 곳에 박혀 있어
갱신 PR이 한쪽만 고쳤고, 그 PR의 CI는 초록이라 어긋남이 드러나지 않았다.

여기서 필요한 것은 **해석(resolution)이 옳은지**가 아니라 **선언이 옮겨졌는지**다.
그건 두 파일을 읽어 비교하면 된다. 저장소가 이미 쓰는 방식이기도 하다
(``test_testplan_sync.py`` · ``test_compose_env_wiring.py``).

## 무엇을 비교하는가

``uv.lock``의 루트 패키지 ``[package.metadata].requires-dist``와 ``pyproject.toml``의
선언을 **이름 · extras · 버전 범위**까지 대조한다. 해석된 버전(``[[package]]``의
``version``)은 보지 않는다 — 그건 uv가 정할 몫이고, 범위 안에서 달라지는 것이 정상이다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_UV_LOCK = _ROOT / "uv.lock"

#: ``pyjwt[crypto]>=2.8,<3.0`` → 이름 · extras · 버전 범위
_REQUIREMENT = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?:\[(?P<extras>[^\]]*)\])?\s*(?P<spec>.*?)\s*$"
)


def normalize(name: str) -> str:
    """PEP 503 정규화. ``python_multipart``와 ``python-multipart``를 같게 본다."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(raw: str) -> tuple[str, tuple[str, ...], str]:
    """요구사항 문자열을 ``(이름, extras, 버전범위)``로 나눈다."""
    # 환경 마커는 이름·범위 뒤에 온다. 현재 pyproject에는 없고, 생기면 그때 정한다.
    head = raw.split(";", 1)[0]
    matched = _REQUIREMENT.match(head)
    assert matched is not None, f"요구사항을 해석하지 못했습니다: {raw!r}"
    extras_raw = matched.group("extras") or ""
    extras = tuple(sorted(normalize(e.strip()) for e in extras_raw.split(",") if e.strip()))
    return normalize(matched.group("name")), extras, matched.group("spec")


def pyproject_declarations() -> dict[str, tuple[str, tuple[str, ...], str]]:
    """``pyproject.toml``의 런타임 + dev 선언. 키는 정규화된 이름."""
    with _PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    project = data["project"]
    raw: list[str] = list(project.get("dependencies", []))
    for extra_items in project.get("optional-dependencies", {}).values():
        raw.extend(extra_items)

    declarations = {}
    for item in raw:
        name, extras, spec = parse_requirement(str(item))
        declarations[name] = (name, extras, spec)
    return declarations


def _root_package(lock: dict) -> dict:
    """``uv.lock``에서 이 프로젝트 자신의 항목을 찾는다."""
    with _PYPROJECT.open("rb") as handle:
        project_name = normalize(tomllib.load(handle)["project"]["name"])
    for package in lock.get("package", []):
        if normalize(str(package.get("name", ""))) == project_name:
            return package
    raise AssertionError(f"uv.lock에 루트 패키지({project_name}) 항목이 없습니다.")


def lock_declarations() -> dict[str, tuple[str, tuple[str, ...], str]]:
    """``uv.lock``이 기록한 선언. 키는 정규화된 이름."""
    with _UV_LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    metadata = _root_package(lock).get("metadata", {})
    declarations = {}
    for entry in metadata.get("requires-dist", []):
        name = normalize(str(entry["name"]))
        extras = tuple(sorted(normalize(e) for e in entry.get("extras", [])))
        declarations[name] = (name, extras, str(entry.get("specifier", "")))
    return declarations


def test_uv_lock이_존재한다() -> None:
    """없어지면 이 검사 전체가 조용히 무의미해진다 — 그 상태를 먼저 막는다.

    `TECH_SPEC §2.5.2`가 lock을 재현성 수단으로 요구하지는 않으나, `README`가
    `uv run pytest`를 테스트 명령으로 지정하고 있어 **uv는 이 저장소의 실행기**다.
    lock을 지우려면 그 결정을 먼저 뒤집어야 한다.
    """
    assert _UV_LOCK.is_file(), (
        "uv.lock이 없습니다. README가 `uv run pytest`를 테스트 명령으로 지정하므로 "
        "uv는 이 저장소의 실행기입니다. 제거하려면 README와 TECH_SPEC §2.5.2를 함께 "
        "정리하십시오."
    )


def test_선언된_의존성이_전부_lock에_있다() -> None:
    """`#399`의 원 결함이다 — `pyjwt`가 pyproject에만 있고 lock에는 없었다."""
    missing = sorted(set(pyproject_declarations()) - set(lock_declarations()))

    assert not missing, (
        f"pyproject.toml에는 있으나 uv.lock에 없는 의존성 {len(missing)}개: {missing}\n"
        "→ `uv lock`을 실행해 갱신한 뒤 함께 커밋하세요."
    )


def test_lock에만_있는_의존성이_없다() -> None:
    """반대 방향. 의존성을 뺐는데 lock에 남으면 필요 없는 패키지가 계속 깔린다."""
    stale = sorted(set(lock_declarations()) - set(pyproject_declarations()))

    assert not stale, (
        f"uv.lock에는 있으나 pyproject.toml에 없는 의존성 {len(stale)}개: {stale}\n"
        "→ `uv lock`을 실행해 갱신한 뒤 함께 커밋하세요."
    )


def test_버전_범위와_extras가_일치한다() -> None:
    """이름만 맞고 범위가 어긋나면 **다른 것을 설치하면서 같은 것처럼 보인다.**"""
    declared = pyproject_declarations()
    locked = lock_declarations()

    mismatched = [
        f"{name}: pyproject={declared[name][1:]} · uv.lock={locked[name][1:]}"
        for name in sorted(set(declared) & set(locked))
        if declared[name] != locked[name]
    ]

    assert not mismatched, "선언이 어긋난 의존성:\n  " + "\n  ".join(mismatched)


def test_해석된_패키지_항목이_존재한다() -> None:
    """선언만 옮겨지고 해석이 빠지면 `uv sync`가 그 자리에서 실패한다."""
    with _UV_LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    resolved = {normalize(str(p.get("name", ""))) for p in lock.get("package", [])}

    unresolved = sorted(set(pyproject_declarations()) - resolved)

    assert not unresolved, (
        f"uv.lock에 해석된 항목이 없는 의존성: {unresolved}\n"
        "→ `uv lock`을 실행해 갱신한 뒤 함께 커밋하세요."
    )


def test_pyjwt가_양쪽에_있다() -> None:
    """`#399`가 보고한 그 패키지다. 회귀하면 여기서 이름으로 드러난다."""
    assert "pyjwt" in pyproject_declarations()
    assert "pyjwt" in lock_declarations()
