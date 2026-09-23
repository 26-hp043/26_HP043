"""배포는 **한 커밋**으로 고정된다 (`#1633` · `F-10`).

## 무엇을 막는가

배포 워크플로는 이미지에 `GITHUB_SHA`를 태그로 붙이면서, 원격 호스트 두 곳은
`git fetch … main`으로 **그 순간의 `main`**을 받아 갔다. 빌드가 끝난 뒤 다른 PR이
머지되면 **이미지 A와 실행 코드 B**가 함께 돌고, 두 호스트가 받는 시점이 다르면
**호스트끼리도 어긋난다.**

이 저장소는 밤사이 PR을 연달아 머지하므로 「빌드 뒤 main 이동」은 드문 일이 아니라
**흔한 일**이다.

## 왜 파일 검사인가

배포는 실행해야 재현되는데, 그 실행이 **운영 서버를 건드린다.** 재현 대신 **배포가
무엇을 받아 가는지**를 파일에서 본다 — 원격이 `main`이 아니라 넘겨받은 SHA를 받고,
받은 것이 그 SHA인지 확인하고 아니면 멈추는지.

`PyYAML`을 들이지 않는 판단은 `test_workflow_timeouts.py`와 같다.
"""

from __future__ import annotations

from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"


def _text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def test_the_workflow_is_read_at_all():
    """파일을 못 읽으면 아래 검사가 **빈 문자열을 훑어 통과**한다."""
    body = _text()
    assert "deploy-db" in body and "deploy-app" in body, "배포 워크플로의 잡 이름을 찾지 못했다"


def test_remote_hosts_do_not_fetch_a_branch():
    """원격이 `main`을 받아 가지 않는다 — 브랜치는 움직인다."""
    offending = [
        line.strip()
        for line in _text().splitlines()
        if "git fetch" in line and line.rstrip().endswith("main")
    ]

    assert offending == [], "원격이 브랜치를 받아 간다:\n  " + "\n  ".join(offending)


def test_both_remote_hosts_receive_the_run_sha():
    """두 호스트 모두 **이 실행의 커밋**을 넘겨받는다."""
    body = _text()
    assert body.count("DEPLOY_SHA='${{ github.sha }}'") == 2, (
        "`DEPLOY_SHA`를 넘기는 자리가 둘이 아니다 — db-01·app-01 양쪽에 있어야 한다"
    )
    pinned = 'git fetch "https://x-access-token:${GH_TOKEN}@github.com'
    assert body.count(pinned + '/${GH_REPO}.git" "${DEPLOY_SHA}"') == 2


def test_a_mismatch_stops_the_deploy():
    """받은 것이 그 커밋이 아니면 **멈춘다.**

    확인 없이 넘어가면 「고정했다」는 말만 남고 실제로는 다른 코드가 돈다. 멈추면
    이전 컨테이너가 그대로 남아 서비스는 살아 있다.
    """
    body = _text()
    assert body.count('if [ "${got}" != "${DEPLOY_SHA}" ]; then') == 2
    assert body.count("exit 1") >= 2
