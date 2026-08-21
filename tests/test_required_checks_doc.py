"""CI 잡과 `AGENTS §7` required check 표의 동기화 검증 (#402).

## 무엇을 막는가

``#393``이 배포 산출물 검증 잡(``docker``)을 추가했는데, **브랜치 보호의 required
check에는 올라가지 않았다.** 잡은 돌지만 실패해도 머지가 막히지 않는 상태가 됐고,
그 사실이 저장소 문서 어디에도 없어 **확인할 방법이 없었다.**

`#393` PR 본문에 「후속 대응 필요」로 적혀 있었으나, PR 본문은 머지되면 목록에서
멀어진다. 그래서 ``#402``가 열릴 때까지 남아 있었다.

**잡이 돌지만 아무것도 막지 않는 상태가 가장 나쁘다.** 빨간불이 떠도 머지가 되면
다음 사람은 그 불을 무시하거나 뒤늦게 발견한다.

## 무엇을 검사하는가

**PR에서 도는 모든 워크플로**의 잡이 ``AGENTS §7``의 required check 표에 **한 행씩**
있는지 본다. 새 잡을 만들면서 표에 적지 않으면 여기서 실패한다 — 그러면 「required로
올릴 것인가」를 그 자리에서 정하게 된다.

종전에는 ``ci.yml`` 한 파일만 봤다. ``#600``이 ``pr-title.yml``을 별도 파일로 낸 것이
계기다 — PR 제목 검사는 ``edited`` 이벤트가 필요한데, 그걸 ``ci.yml``의 ``on:``에
넣으면 **제목·본문을 고칠 때마다 CI 4종이 전부 다시 돈다.** 파일을 나누는 것이 맞고,
그러면 이 가드가 새 파일을 보지 못한다.

``pull_request``로 돌지 않는 워크플로는 제외한다. ``audit.yml``이 그렇다 — 외부
advisory DB가 갱신되면 코드를 고치지 않은 날에도 실패하므로 **일부러** 머지 게이트에
두지 않았다(``#160``). 머지를 막을 수 없는 잡을 required 표에 적으라고 요구하면 표가
「무엇이 머지를 막는가」를 더 이상 말하지 않게 된다.

## 무엇을 검사하지 않는가

**실제 브랜치 보호 설정과 대조하지 않는다.** 그건 GitHub API 호출이라 네트워크와
토큰이 필요하고, 오프라인·포크에서 테스트가 깨진다. 여기서 잠그는 것은
**「결정이 기록됐는가」**이지 「설정이 그렇게 됐는가」가 아니다. 후자는 사람이
`AGENTS §7`의 조회 명령으로 확인한다.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_AGENTS = _ROOT / "AGENTS.md"

#: ``  jobname:`` — 잡 정의는 2칸 들여쓰기다.
_JOB = re.compile(r"^  (?P<name>[A-Za-z0-9_-]+):\s*$")
#: ``  | `docker` | ⏸ 미적용 | … |`` — 표의 첫 칸이 백틱으로 감싼 잡 이름이다.
_ROW = re.compile(r"^\s*\|\s*`(?P<name>[A-Za-z0-9_-]+)`\s*\|")


#: ``  pull_request:`` — ``on:`` 블록 안의 트리거는 2칸 들여쓰기다.
_PR_TRIGGER = re.compile(r"^  pull_request:\s*$")


def _runs_on_pull_request(path: Path) -> bool:
    """``on:`` 블록에 ``pull_request`` 트리거가 있는가.

    ``jobs:``를 만나기 전까지만 본다 — 잡 이름이 우연히 같아도 걸리지 않게 한다.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("jobs:"):
            return False
        if _PR_TRIGGER.match(line):
            return True
    return False


def gating_workflows() -> list[Path]:
    """머지를 막을 수 있는 워크플로 = ``pull_request``로 도는 것."""
    return [p for p in sorted(_WORKFLOWS.glob("*.yml")) if _runs_on_pull_request(p)]


def ci_jobs() -> list[str]:
    """PR에서 도는 워크플로의 잡 이름. 각 파일의 ``jobs:`` 블록 안만 본다."""
    jobs = []
    for path in gating_workflows():
        in_jobs = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("jobs:"):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            if line and not line.startswith(" ") and not line.startswith("#"):
                break
            matched = _JOB.match(line)
            if matched:
                jobs.append(matched.group("name"))
    return jobs


def documented_jobs() -> list[str]:
    """``AGENTS.md``의 required check 표에 적힌 잡 이름."""
    text = _AGENTS.read_text(encoding="utf-8")
    marker = "| CI 잡 | required check | 근거 |"
    assert marker in text, (
        "AGENTS.md에서 required check 표를 찾지 못했습니다. "
        "표 머리글이 바뀌었다면 이 테스트도 함께 고치세요 (#402)."
    )
    section = text[text.index(marker) :]
    names = []
    for line in section.splitlines()[2:]:  # 머리글 + 구분선 건너뜀
        if not line.strip().startswith("|"):
            break
        matched = _ROW.match(line)
        if matched:
            names.append(matched.group("name"))
    return names


def test_ci_잡을_읽을_수_있다() -> None:
    """파서가 깨지면 아래 검사들이 조용히 통과한다 — 그 상태를 먼저 막는다."""
    gating = gating_workflows()
    jobs = ci_jobs()

    assert gating, (
        f"{_WORKFLOWS}에서 `pull_request`로 도는 워크플로를 찾지 못했습니다. "
        "`on:` 블록의 표기가 바뀌었다면 이 테스트도 함께 고치세요 (#600)."
    )
    assert len(jobs) >= 3, f"워크플로에서 읽은 잡이 너무 적습니다: {jobs}"


def test_모든_ci_잡이_표에_있다() -> None:
    """새 잡을 만들면서 required 여부를 정하지 않는 것을 막는다 — `#393`이 그 사례다."""
    missing = sorted(set(ci_jobs()) - set(documented_jobs()))

    assert not missing, (
        f"`AGENTS §7` required check 표에 없는 CI 잡 {len(missing)}개: {missing}\n"
        "→ 표에 행을 추가하고 **required로 올릴 것인지 그 자리에서 정하세요.** "
        "잡이 돌지만 아무것도 막지 않는 상태가 가장 나쁩니다 (#402)."
    )


def test_표에만_있는_잡이_없다() -> None:
    """반대 방향. 잡을 지웠는데 표에 남으면 없는 것을 막고 있다고 오해한다."""
    stale = sorted(set(documented_jobs()) - set(ci_jobs()))

    assert not stale, (
        f"PR에서 도는 워크플로에 없는데 표에 남은 잡: {stale}\n→ 표에서 그 행을 지우세요."
    )
