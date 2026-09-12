#!/usr/bin/env python3
"""파일별 커버리지 하한 (#955 · `#911` B안).

## 왜 필요한가

CI 게이트(``--cov-fail-under=90``)는 **전체 합계만** 본다. 합계가 96%여도 파일
하나가 60%대로 남을 수 있고, 이 저장소에서 **실제로 두 번 오래 남았다.**

===================  =====================================================
 `#871`               `auth.py` 41~58% — 라우트 본문이 한 번도 실행되지
                      않는 결함이었는데 합계 게이트가 통과시켰다
 `#911`               `reports.py` 61% · `exports.py` 65% — 계측을 고쳐도
                      그대로였다. **전부 실제 검사 공백**이었다
===================  =====================================================

둘 다 「합계는 통과인데 그 파일은 사실상 안 덮여 있다」였다. 합계 게이트는 구조상
그것을 볼 수 없다 — 5,900문장 중 69문장이 비어도 합계는 1pp도 안 움직인다.

## 두 기준 중 **하나**만 넘으면 통과다

작은 파일에 비율만 걸면 **한 줄만 안 덮여도 빨갛다.** 8문장짜리 파일의 1문장은
87.5%다. 그것은 검사 공백이 아니라 산술이다.

====================  ====================================================
 비율                   :data:`FLOOR_PERCENT` 이상
 **또는** 미커버 문장 수   :data:`FLOOR_MISSING` 이하
====================  ====================================================

그래서 **큰 파일은 비율로, 작은 파일은 절대 문장 수로** 잡힌다. 파일 크기에 따라
대상에서 빼지 않는다 — 빼면 그 크기 아래가 통째로 사각지대가 된다.

## 예외는 **사유와 이슈 번호**를 달고 목록에 있어야 한다

:data:`KNOWN_BELOW_FLOOR`가 그 목록이다. 항목마다 **그 파일의 개별 하한**을 적는다.

- 그 하한 **아래로 떨어지면** 실패한다 — 예외가 「영원히 면제」가 되지 않는다.
- 전역 하한을 **넘어서면** 실패한다 — 낡은 목록은 거짓말이다. 지우라고 말한다.
- 목록에 없는 파일이 하한 아래면 실패한다.

## 명령

::

    python3 scripts/check_coverage_floor.py                  # coverage.xml을 읽는다
    python3 scripts/check_coverage_floor.py --report         # 전 파일 수치를 찍는다
    python3 scripts/check_coverage_floor.py path/to/cov.xml

``coverage.xml``은 CI가 이미 만든다(``--cov-report=xml``). **검사를 다시 돌리지
않는다** — 게이트 한 단계가 늘 뿐이다.

표준 라이브러리만 쓴다(``db_backup.py``·``purge_expired.py``와 같은 판).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

#: 비율 하한. 합계 게이트(90)보다 낮게 둔다 — 새 파일이 들어온 날 바로 빨개지면
#: 하한을 낮추는 압력이 생긴다. `#871`·`#911`이 남긴 60%대는 확실히 잡힌다.
FLOOR_PERCENT = 80.0

#: 미커버 문장 수 상한. 이 이하면 비율과 무관하게 통과다.
#: 작은 파일의 산술 노이즈를 없애되, 큰 파일의 구멍은 비율 쪽이 잡는다.
FLOOR_MISSING = 5

#: 기본 입력 — CI의 ``--cov-report=xml``이 만드는 자리.
DEFAULT_REPORT = "coverage.xml"


@dataclass(frozen=True)
class Exemption:
    """하한 아래인 파일 하나의 예외.

    :param floor: 이 파일에 적용할 개별 하한(%). **현재 값보다 낮게** 적어
        측정 요동으로 깜빡이지 않게 하되, 실질적 후퇴는 잡히게 한다.
    :param reason: 왜 낮은지와 **이슈 번호**. 「TODO」로 채우면 목록이
        그저 통과용이 된다.
    """

    floor: float
    reason: str


#: 하한 아래인 것이 **알려져 있고 사유가 있는** 파일.
#:
#: ⚠️ 올라가면 여기서 **빼야 한다.** 남겨 두면 검사가 거짓말한다.
#:
#: 2026-09-13 실측(157파일 · 합계 96.5%)에서 걸린 셋이다. 분포에 **77.3% → 83.3%**
#: 빈 구간이 있어 :data:`FLOOR_PERCENT` 80이 어느 무리도 가르지 않는다.
KNOWN_BELOW_FLOOR: dict[str, Exemption] = {
    "cii_platform/auth/dependencies.py": Exemption(
        65.0,
        "get_current_user의 DB 조회 본문(132~162)이 도달하지 않는다 — auth_middleware가 "
        "모든 비공개 경로에서 request.state.session_user를 먼저 채우므로 캐시 확인에서 "
        "반환된다. 검사 공백이 아니라 **중복 경로**다. 정리 판단은 #955 후속",
    ),
    "cii_platform/services/chat_tools.py": Exemption(
        60.0,
        "도구 4종 본문이 오케스트레이션 대역(FakeProvider)으로만 지나가고 "
        "DB를 붙인 실행 경로가 없다 — #121에서 신설한 계층이다",
    ),
    "cii_platform/depcheck.py": Exemption(
        70.0,
        "main()은 컨테이너 기동 시에만 도는 진입점이다(Dockerfile CMD · #523). "
        "실행은 docker 잡이 매번 하고, 단위 검사 대상은 위쪽 순수 함수들이다",
    ),
}


def _rate(elem: ET.Element) -> tuple[int, int]:
    """``<class>`` 하나의 (전체 문장, 미커버 문장)."""
    lines = elem.findall("./lines/line")
    total = len(lines)
    missing = sum(1 for line in lines if line.get("hits") == "0")
    return total, missing


def normalize(name: str) -> str:
    """경로를 ``cii_platform/...`` 한 가지로 맞춘다.

    ⚠️ CI는 설치된 패키지를 재고(``--cov=cii_platform``), 로컬에서는 소스를 직접
    재는 경우가 많다(``--cov=src/cii_platform``). 그러면 같은 파일이
    ``cii_platform/api/routes/auth.py``와 ``src/cii_platform/…`` 두 이름으로 나와
    **예외 목록이 한쪽에서만 맞는다.** 맨 앞 ``src/``만 떼면 둘이 같아진다.
    """
    return name[4:] if name.startswith("src/") else name


def collect(report: Path) -> dict[str, tuple[int, int]]:
    """``coverage.xml``에서 파일별 (전체 문장, 미커버 문장)을 모은다.

    같은 파일이 여러 ``<package>``에 나뉘어 나오는 경우가 있어 **합산**한다.
    """
    root = ET.parse(report).getroot()
    out: dict[str, tuple[int, int]] = {}
    for cls in root.iterfind(".//class"):
        raw = cls.get("filename")
        if not raw:
            continue
        name = normalize(raw)
        total, missing = _rate(cls)
        prev = out.get(name, (0, 0))
        out[name] = (prev[0] + total, prev[1] + missing)
    return out


def percent(total: int, missing: int) -> float:
    """빈 파일은 100%로 본다 — 잴 것이 없다."""
    if total == 0:
        return 100.0
    return (total - missing) / total * 100.0


def evaluate(files: dict[str, tuple[int, int]]) -> list[str]:
    """실패 사유를 사람이 읽을 문장으로 돌려준다. 빈 목록이면 통과다."""
    problems: list[str] = []
    seen_exempt: set[str] = set()

    for name in sorted(files):
        total, missing = files[name]
        pct = percent(total, missing)
        exemption = KNOWN_BELOW_FLOOR.get(name)

        if exemption is not None:
            seen_exempt.add(name)
            if pct >= FLOOR_PERCENT or missing <= FLOOR_MISSING:
                problems.append(
                    f"{name}: {pct:.1f}% — 하한을 넘었다. "
                    f"KNOWN_BELOW_FLOOR에서 **빼라**(낡은 예외는 거짓말이다)"
                )
            elif pct < exemption.floor:
                problems.append(
                    f"{name}: {pct:.1f}% < 개별 하한 {exemption.floor:.1f}% — "
                    f"예외로 둔 뒤 더 내려갔다 ({exemption.reason})"
                )
            continue

        if pct < FLOOR_PERCENT and missing > FLOOR_MISSING:
            problems.append(
                f"{name}: {pct:.1f}% ({missing}/{total}문장 미커버) — "
                f"하한 {FLOOR_PERCENT:.0f}% 미만이고 미커버가 {FLOOR_MISSING}문장을 넘는다. "
                f"검사를 채우거나, 사유와 이슈 번호를 달아 KNOWN_BELOW_FLOOR에 넣어라"
            )

    for name in sorted(set(KNOWN_BELOW_FLOOR) - seen_exempt):
        problems.append(f"{name}: 보고서에 없는 파일이 KNOWN_BELOW_FLOOR에 있다 — 지워라")

    return problems


def validate_exemptions() -> list[str]:
    """예외 목록 자체를 본다 — 사유가 비어 있으면 목록이 통과용이 된다."""
    problems: list[str] = []
    for name, exemption in sorted(KNOWN_BELOW_FLOOR.items()):
        if len(exemption.reason) < 20:
            problems.append(f"{name}: 사유가 너무 짧다 — 무엇이 왜 안 덮이는지 적어라")
        if "#" not in exemption.reason:
            problems.append(f"{name}: 사유에 이슈 번호가 없다")
        if not 0.0 <= exemption.floor < FLOOR_PERCENT:
            problems.append(
                f"{name}: 개별 하한 {exemption.floor}이 0~{FLOOR_PERCENT} 밖이다 — "
                f"전역 하한 이상이면 예외일 이유가 없다"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("report", nargs="?", default=DEFAULT_REPORT)
    parser.add_argument("--report", dest="show", action="store_true", help="전 파일 수치를 찍는다")
    args = parser.parse_args(argv)

    path = Path(args.report)
    if not path.exists():
        print(f"커버리지 보고서가 없습니다: {path}", file=sys.stderr)
        return 2

    files = collect(path)
    if not files:
        print(
            f"보고서에 파일이 하나도 없습니다: {path} — 측정이 비었는지 확인하세요",
            file=sys.stderr,
        )
        return 2

    if args.show:
        for name in sorted(files, key=lambda n: percent(*files[n])):
            total, missing = files[name]
            print(f"{percent(total, missing):6.1f}%  {missing:4d}/{total:4d}  {name}")

    problems = validate_exemptions() + evaluate(files)
    if problems:
        print(f"\n파일별 커버리지 하한 위반 {len(problems)}건 (#955)\n", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"파일별 커버리지 하한 통과 — {len(files)}개 파일 (#955)")
    return 0


if __name__ == "__main__":  # pragma: no cover - 진입점
    raise SystemExit(main())
