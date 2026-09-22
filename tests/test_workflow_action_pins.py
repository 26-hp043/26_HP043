"""워크플로가 쓰는 액션은 **커밋 SHA로 고정한다** (`#1638` · `F-12` 결정).

## 무엇을 막는가

``uses: actions/checkout@v7``은 **태그**다. 태그는 움직인다 — 같은 `v7`이 어제와 오늘
다른 코드를 가리킬 수 있고, 태그를 옮길 수 있는 사람은 액션 저장소 쪽이다. 이
저장소의 배포 워크플로는 **GHCR 쓰기 권한과 SSH 개인키**를 쥐고 돌므로, 「검토한
코드와 실행되는 코드가 같다」를 태그에 맡길 수 없다.

SHA로 고정하면 그 보장이 생긴다. 갱신 경로는 막히지 않는다 — Dependabot이 SHA
형식을 읽고 새 SHA로 PR을 연다(실측: `#1638` 결정 코멘트).

## 왜 테스트인가

고정은 **한 번 해 두면 눈에 띄지 않는다.** 새 잡을 추가하며 태그로 적어도 그 PR의
CI는 초록이고, 어긋났다는 사실은 **누군가 태그를 옮길 때까지** 드러나지 않는다.

저장소 설정 `sha_pinning_required`를 켜면 실행 단계에서도 막히지만 그것은 **관리
권한**이 필요하고, 설정과 파일이 어긋나는 것 자체를 여기서 본다.

## 파서를 직접 두는 이유

`PyYAML`은 이 저장소의 의존성이 아니다(`test_workflow_timeouts.py`와 같은 판단).
필요한 것은 `uses:` 줄 하나뿐이라 정규식으로 읽는다.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: `uses: owner/repo@ref` — 로컬 액션(`./`)과 도커 액션(`docker://`)은 대상이 아니다.
USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>[A-Za-z0-9][\w.-]*/[\w.-]+@\S+)", re.M)

#: 40자리 16진수. GitHub이 받는 유일한 「움직이지 않는」 참조다.
SHA = re.compile(r"^[0-9a-f]{40}$")


def _refs() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for match in USES.finditer(path.read_text(encoding="utf-8")):
            found.append((path.name, match.group("ref")))
    return found


def test_the_workflows_are_read_at_all():
    """파서가 깨져 0건이 되면 **아래 검사가 빈 것끼리 비교해 통과한다.**"""
    refs = _refs()
    assert len(refs) >= 10, f"`uses:` 줄을 {len(refs)}개만 읽었다 — 파서가 깨졌는지 본다"


def test_every_action_is_pinned_to_a_commit_sha():
    """태그로 적힌 액션이 하나도 없다."""
    unpinned = [f"{name}: {ref}" for name, ref in _refs() if not SHA.match(ref.split("@", 1)[1])]

    assert unpinned == [], "커밋 SHA로 고정하지 않은 액션이 있다:\n  " + "\n  ".join(unpinned)


def test_each_pin_says_which_version_it_is():
    """SHA 옆에 **버전 주석**이 있다 — 없으면 무엇을 고정했는지 사람이 읽을 수 없다.

    `# v7`처럼 적는다. Dependabot도 이 주석을 갱신한다.
    """
    missing: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = USES.match(line)
            if match is None:
                continue
            if SHA.match(match.group("ref").split("@", 1)[1]) and "#" not in line.split("@", 1)[1]:
                missing.append(f"{path.name}: {line.strip()}")

    assert missing == [], "고정한 SHA가 어느 버전인지 적혀 있지 않다:\n  " + "\n  ".join(missing)
