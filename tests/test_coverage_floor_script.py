"""파일별 커버리지 하한 스크립트 (`#955` · IT-COV-001~009).

## 왜 검사가 필요한가

이 스크립트는 **CI를 빨갛게 만드는 물건**이다. 잘못 만들면 두 방향으로 나쁘다.

=====================  ====================================================
 너무 헐거우면            `#871`·`#911`이 그랬듯 **60%대가 조용히 남는다**
 너무 빡빡하면            8문장짜리 파일의 1문장에 CI가 걸려 **하한을 낮추는
                        압력**이 생긴다. 그러면 게이트가 있으나 마나다
=====================  ====================================================

그래서 **두 기준 중 하나**(비율 또는 미커버 문장 수)를 쓰는데, 그 「또는」이
제대로 걸리는지를 여기서 본다.

## 예외 목록이 거짓말하지 않는가

이 저장소가 쓰는 형태다(`test_fuel_table_sync_db.py`·`test_regulation_ship_type_sync_db.py`).
**올라간 뒤 목록에서 안 빼면 실패**해야 한다 — 안 그러면 목록이 영구 면제가 된다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_coverage_floor.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_coverage_floor", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_coverage_floor"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _write(tmp_path: Path, entries: dict[str, tuple[int, int]]) -> Path:
    """(전체 문장, 미커버 문장) → ``coverage.xml``(Cobertura) 파일."""
    classes = []
    for name, (total, missing) in entries.items():
        lines = "".join(
            f'<line number="{i}" hits="{0 if i <= missing else 1}"/>' for i in range(1, total + 1)
        )
        classes.append(f'<class filename="{name}"><lines>{lines}</lines></class>')
    path = tmp_path / "coverage.xml"
    path.write_text(
        f"<coverage><packages><package><classes>{''.join(classes)}</classes>"
        "</package></packages></coverage>",
        encoding="utf-8",
    )
    return path


def test_it_cov_001_a_large_file_below_the_floor_fails(tmp_path, monkeypatch):
    """IT-COV-001 — ⚠️ **큰 파일의 비율 구멍을 잡는다**.

    `#911`의 실물이다 — `reports.py` 61%. 합계 게이트가 통과시킨 바로 그 형태.
    """
    monkeypatch.setattr(gate, "KNOWN_BELOW_FLOOR", {})
    files = gate.collect(_write(tmp_path, {"src/a.py": (100, 39)}))
    problems = gate.evaluate(files)
    assert problems, "61%가 통과했다"
    assert "61.0%" in problems[0], problems


def test_it_cov_002_a_small_file_with_few_missing_passes(tmp_path, monkeypatch):
    """IT-COV-002 — 작은 파일은 **미커버 문장 수**로 통과한다.

    8문장 중 1문장은 87.5%다. 검사 공백이 아니라 산술이다. 여기서 걸리면
    **하한을 낮추라는 압력**이 생기고, 그러면 `#911` 같은 구멍이 다시 통과한다.
    """
    monkeypatch.setattr(gate, "KNOWN_BELOW_FLOOR", {})
    files = gate.collect(_write(tmp_path, {"src/tiny.py": (8, 3)}))
    assert gate.evaluate(files) == [], "37.5%지만 미커버 3문장이라 통과해야 한다"


def test_it_cov_003_a_small_file_with_many_missing_still_fails(tmp_path, monkeypatch):
    """IT-COV-003 — ⚠️ **작다고 면제되지 않는다**.

    크기로 대상에서 빼면 그 크기 아래가 통째로 사각지대가 된다. 미커버가
    상한을 넘으면 작아도 잡힌다.
    """
    monkeypatch.setattr(gate, "KNOWN_BELOW_FLOOR", {})
    files = gate.collect(_write(tmp_path, {"src/tiny.py": (10, 9)}))
    assert gate.evaluate(files), "미커버 9문장이 통과했다"


def test_it_cov_004_an_exempt_file_passes_but_a_further_drop_fails(tmp_path, monkeypatch):
    """IT-COV-004 — 예외는 **더 내려가면** 실패한다.

    예외가 「영원히 면제」가 되면 목록이 값을 잃는다.
    """
    monkeypatch.setattr(
        gate,
        "KNOWN_BELOW_FLOOR",
        {"legacy.py": gate.Exemption(60.0, "라우트 본문 미도달 잔여 — #828")},
    )
    ok = gate.collect(_write(tmp_path, {"src/legacy.py": (100, 35)}))
    assert gate.evaluate(ok) == [], "65%는 개별 하한 60% 위라 통과해야 한다"

    dropped = gate.collect(_write(tmp_path, {"src/legacy.py": (100, 45)}))
    assert gate.evaluate(dropped), "55%로 떨어졌는데 통과했다"


def test_it_cov_005_a_recovered_file_must_leave_the_list(tmp_path, monkeypatch):
    """IT-COV-005 — ⚠️ **낡은 예외는 거짓말이다**.

    올라간 뒤에도 목록에 남아 있으면 실패한다 — 그 파일은 더 이상 감시받지
    않는데 목록은 「알려진 공백」이라고 말한다(`#773`·`#834`와 같은 규칙).
    """
    monkeypatch.setattr(
        gate,
        "KNOWN_BELOW_FLOOR",
        {"fixed.py": gate.Exemption(60.0, "검사 공백 — #911")},
    )
    files = gate.collect(_write(tmp_path, {"src/fixed.py": (100, 5)}))
    problems = gate.evaluate(files)
    assert problems, "95%인데 목록에 남아 있는 것이 통과했다"
    assert "빼라" in problems[0], problems


def test_it_cov_006_a_stale_path_in_the_list_fails(tmp_path, monkeypatch):
    """IT-COV-006 — 보고서에 없는 경로가 목록에 있으면 실패한다.

    파일을 지우거나 옮긴 뒤 목록만 남으면, 그 항목은 **아무것도 감시하지 않으면서**
    목록을 길게 만든다.
    """
    monkeypatch.setattr(
        gate,
        "KNOWN_BELOW_FLOOR",
        {"gone.py": gate.Exemption(60.0, "지워진 파일 — #955")},
    )
    files = gate.collect(_write(tmp_path, {"src/a.py": (100, 1)}))
    assert gate.evaluate(files), "없는 경로가 통과했다"


def test_it_cov_007_every_exemption_carries_a_reason(monkeypatch):
    """IT-COV-007 — 목록 항목마다 **사유와 이슈 번호**가 있다.

    「TODO」로 채우면 목록이 그저 통과용이 된다(`#773`·`#834`와 같은 규칙).
    """
    monkeypatch.setattr(gate, "KNOWN_BELOW_FLOOR", {"src/a.py": gate.Exemption(60.0, "TODO")})
    assert gate.validate_exemptions(), "「TODO」가 통과했다"

    monkeypatch.setattr(
        gate,
        "KNOWN_BELOW_FLOOR",
        {"src/a.py": gate.Exemption(60.0, "짧지 않은 사유를 적었지만 번호가 없다")},
    )
    assert gate.validate_exemptions(), "이슈 번호 없는 사유가 통과했다"


def test_it_cov_008_src_prefixed_paths_are_the_same_file(tmp_path, monkeypatch):
    """IT-COV-008 — ⚠️ **`src/` 접두사가 붙어도 같은 파일이다**.

    CI는 설치된 패키지를(`--cov=cii_platform`), 로컬은 소스를 직접 재는 경우가
    많다(`--cov=src/cii_platform`). 맞추지 않으면 **예외 목록이 CI에서만 맞고
    로컬에서는 「없는 경로」로 실패**하거나 그 반대가 된다.
    """
    monkeypatch.setattr(
        gate,
        "KNOWN_BELOW_FLOOR",
        {"cii_platform/a.py": gate.Exemption(60.0, "검사 공백 — #911")},
    )
    files = gate.collect(_write(tmp_path, {"src/cii_platform/a.py": (100, 35)}))
    assert "cii_platform/a.py" in files, files
    assert gate.evaluate(files) == []


def test_it_cov_009_the_real_list_is_valid():
    """IT-COV-009 — 저장소의 실제 목록이 규칙을 만족한다.

    위 검사들은 `monkeypatch`한 목록을 본다. **실물**도 봐야 한다.
    """
    assert gate.validate_exemptions() == []
