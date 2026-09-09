"""워크플로 잡의 실행 상한 검증 (#533).

## 무엇을 막는가

2026-08-18에 ``test`` 잡이 ``apt-get update``에서 멈춰 **한 번에 5시간 59분 50초**를
태웠다. 같은 날 같은 자리에서 5번 걸렸고, 헛돈 시간은 약 7시간이다.

문제는 멈춘 것 자체가 아니라 **자동으로 끝나지 않은 것**이다. 워크플로 어디에도
``timeout-minutes``가 없어 GitHub 기본 상한인 6시간까지 갔고, 그 사이 잡은 실패가
아니라 **실행 중**이었다 — 그래서 알림도 오지 않았고 사람이 알아채고 취소해야 했다.

정상일 때 같은 단계는 **9~13초**다. 9초에서 6시간까지 벌어진다.

## 왜 테스트로 잠그는가

상한은 **한 번 넣으면 눈에 띄지 않는 값**이다. 새 잡을 추가하면서 빠뜨려도
그 PR의 CI는 초록이고, 빠졌다는 사실은 **다음에 멈출 때까지** 드러나지 않는다.
그때는 이미 6시간을 태운 뒤다.

``#478``(ruff 핀 이중화)·``#394``(테스트 인벤토리)와 같은 부류의 가드다 — 어긋남이
사고로 드러나기 전에 드러나게 한다.

## 파서를 직접 두는 이유

``PyYAML``은 이 저장소의 의존성이 아니다. 검사에 필요한 것은 **잡 이름과 그 잡에
``timeout-minutes``가 있는지**뿐이고, 그건 들여쓰기 규칙만으로 읽을 수 있다.
의존성을 하나 늘려 얻을 것이 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: 잡 상한의 허용 범위. 너무 크면 있으나 마나이고, 너무 작으면 정상 실행을 자른다.
#: 현재 가장 긴 잡(docker)이 정상 1분 안쪽이며 25분을 둔다.
MAX_TIMEOUT_MINUTES = 30

#: ``  jobname:`` — 잡 정의는 2칸 들여쓰기다.
_JOB = re.compile(r"^  (?P<name>[A-Za-z0-9_-]+):\s*$")
_TIMEOUT = re.compile(r"^    timeout-minutes:\s*(?P<minutes>\d+)\s*$")


def workflow_files() -> list[Path]:
    return sorted(p for p in _WORKFLOWS.glob("*.yml"))


def jobs_with_timeout(path: Path) -> dict[str, int | None]:
    """``{잡 이름: 상한(분) 또는 None}``. ``jobs:`` 블록 안만 본다."""
    found: dict[str, int | None] = {}
    in_jobs = False
    current: str | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        # 들여쓰기 없는 최상위 키를 만나면 jobs 블록이 끝난 것이다.
        if line and not line.startswith(" ") and not line.startswith("#"):
            break

        job = _JOB.match(line)
        if job:
            current = job.group("name")
            found[current] = None
            continue

        timeout = _TIMEOUT.match(line)
        if timeout and current is not None:
            found[current] = int(timeout.group("minutes"))

    return found


def test_워크플로_파일이_있다() -> None:
    """경로가 바뀌면 이 검사 전체가 조용히 무의미해진다 — 그 상태를 먼저 막는다."""
    assert workflow_files(), f"{_WORKFLOWS}에 워크플로가 없습니다."


def test_모든_잡에_실행_상한이_있다() -> None:
    """빠진 잡은 멈추면 6시간까지 간다 — `#533`이 그 사례다."""
    missing = [
        f"{path.name}:{job}"
        for path in workflow_files()
        for job, minutes in jobs_with_timeout(path).items()
        if minutes is None
    ]

    assert not missing, (
        f"`timeout-minutes`가 없는 잡 {len(missing)}개: {missing}\n"
        "→ 잡의 `runs-on` 아래에 `timeout-minutes: N`을 넣으세요. "
        "없으면 멈췄을 때 GitHub 기본 상한인 6시간까지 갑니다 (#533)."
    )


def test_상한이_지나치게_크지_않다() -> None:
    """상한이 6시간에 가까우면 있으나 마나다."""
    too_large = [
        f"{path.name}:{job}={minutes}분"
        for path in workflow_files()
        for job, minutes in jobs_with_timeout(path).items()
        if minutes is not None and minutes > MAX_TIMEOUT_MINUTES
    ]

    assert not too_large, (
        f"상한이 {MAX_TIMEOUT_MINUTES}분을 넘는 잡: {too_large}\n"
        "→ 실제로 그만큼 걸리는 잡이라면 이 테스트의 상수를 근거와 함께 올리세요."
    )


def test_apt_get을_직접_호출하지_않는다() -> None:
    """`apt-get`은 미러가 응답하지 않으면 **자체 타임아웃 없이 기다린다.**

    그래서 재시도 루프만으로는 듣지 않는다 — 첫 시도가 끝나지 않으므로 두 번째로
    넘어가지 못한다. 반드시 `timeout`으로 잘라야 한다 (`#533`).
    """
    offenders = []
    for path in workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "apt-get" not in stripped:
                continue
            # 주석과 **안내 문구**는 호출이 아니다. 실패 메시지에 명령 이름을 적는 것은
            # 오히려 권장되는 일이라, 그것까지 잡으면 가드가 문구를 검열하게 된다.
            if stripped.startswith("#") or stripped.startswith("echo "):
                continue
            if "timeout " not in stripped:
                offenders.append(f"{path.name}:{number}: {stripped}")

    assert not offenders, (
        "`timeout`으로 감싸지 않은 `apt-get` 호출:\n  " + "\n  ".join(offenders) + "\n"
        "→ `sudo timeout 120 apt-get update` 형태로 감싸세요 (#533)."
    )


def _font_step() -> str:
    """``PDF 폰트 설치`` 스텝의 스크립트 본문 (#908)."""
    text = (_WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "PDF 폰트 설치" in text, "폰트 설치 스텝을 찾지 못했다 — 이름이 바뀌었는지 확인할 것"
    after = text.split("PDF 폰트 설치", 1)[1]
    # 다음 스텝(`      - `)까지가 이 스텝이다.
    return after.split("\n      - ", 1)[0]


def test_폰트_설치_실패는_여전히_잡을_중단시킨다() -> None:
    """`#908`이 옮긴 것은 **중단 지점**이지 방어선이 아니다.

    ``apt-get update`` 실패를 경고로 낮췄으므로, **설치 실패가 여전히 하드 실패인지**를
    못 박는다. 둘 다 경고가 되면 **폰트 없이 CI가 초록으로 통과**하고, 그 상태에서는
    PDF 한글이 tofu로 나오는 회귀를 아무도 잡지 못한다(``#361`` 완료 기준).
    """
    step = _font_step()
    install = step.split("apt-get install", 1)[1]
    assert "::error::" in install, (
        "폰트 설치 실패가 `::error::`로 보고되지 않는다 — 경고로 낮추면 폰트 없이 통과한다 (#361)"
    )
    assert "exit 1" in install, "폰트 설치가 세 번 실패해도 잡이 멈추지 않는다 (#361)"


def test_인덱스_갱신_실패는_잡을_중단시키지_않는다() -> None:
    """러너 이미지의 **무관한 저장소** 하나가 깨져도 잡이 죽지 않아야 한다 (#908).

    ``apt-get update``는 소스 하나만 실패해도 ``exit 1``이다. 2026-09-10에
    ``dl.google.com``의 인덱스가 ``Hash Sum mismatch``를 내 무관한 잡이 죽었고,
    **해시 불일치는 결정적이라 재시도로 낫지 않았다**(재실행에서 동일 실패).

    갱신 구간에 ``exit 1``이 다시 들어오면 같은 사고가 되풀이된다.
    """
    step = _font_step()
    update = step.split("apt-get install", 1)[0]
    assert "exit 1" not in update, (
        "`apt-get update` 실패가 다시 잡을 중단시킨다 — 무관한 저장소 하나로 CI가 죽는다 (#908)"
    )
    assert "::warning::" in update, (
        "갱신 실패가 조용히 지나간다 — 로그에 사유가 남지 않으면 다음 사람이 원인을 찾지 못한다"
    )
