"""시연 동결 — ``DEPLOY_FROZEN``이면 push 자동 배포만 건너뛴다 (`#789` · 결정 E-2).

## 무엇을 막는가

동결(10/9 18:00)을 공지로만 지키면 머지하는 사람 넷 중 한 사람이 몰랐을 때 깨지고, 깨진
사실은 시연장에서 화면이 다를 때에야 드러난다. 그래서 워크플로가 막는다.

## 왜 파일 검사인가

동결을 실제로 켜 보려면 저장소 변수를 바꿔야 하고 그 실행이 운영 배포다. 대신 워크플로가
**무엇을 보고 건너뛰는지**를 파일에서 본다 — `test_deploy_host_key_pinning.py`와 같은 판단이다.

* 배포 진입 잡 둘(`preflight` · `deploy-frontend`)이 같은 동결 조건을 가진다
* 조건이 **push만** 건너뛴다 — 수동 실행(예외 배포)은 막지 않는다
* 백엔드 뒤 잡들은 `preflight`에 걸려 함께 건너뛴다(따로 조건을 두지 않아도 된다)
* 건너뛴 사실을 남기는 잡이 있다 — 조용히 아무것도 안 하면 「배포가 고장 났다」로 읽힌다
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
OPERATIONS = _ROOT / "docs" / "OPERATIONS.md"

#: 동결이 아닐 때만 돈다 — 수동 실행이거나, 변수가 정확히 'true'가 아니거나.
FROZEN_GUARD = "github.event_name != 'push' || vars.DEPLOY_FROZEN != 'true'"
#: 배포의 두 입구. 백엔드 쪽 나머지는 preflight에 needs로 걸린다.
ENTRY_JOBS = ("preflight", "deploy-frontend")


def _text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _job(name: str) -> str:
    """`jobs:` 아래 들여쓰기 2칸의 잡 블록 하나를 잘라 낸다."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", _text(), re.S | re.M)
    assert match, f"잡 `{name}`을 찾지 못했다"
    return match.group(1)


def _if(block: str) -> str | None:
    match = re.search(r"^    if: (.+)$", block, re.M)
    return match.group(1).strip() if match else None


@pytest.mark.parametrize("job", ENTRY_JOBS)
def test_entry_jobs_skip_only_frozen_pushes(job: str):
    """배포 입구 둘이 같은 조건 — push이면서 DEPLOY_FROZEN == 'true'일 때만 건너뛴다."""
    assert _if(_job(job)) == FROZEN_GUARD


def test_manual_dispatch_is_never_frozen():
    """조건의 첫 항이 push가 아닌 실행(수동 실행)을 통과시킨다 — 예외 배포 경로가 산다."""
    assert FROZEN_GUARD.startswith("github.event_name != 'push' ||")
    assert "workflow_dispatch:" in _text()


def test_backend_jobs_hang_off_preflight():
    """build · deploy-db · deploy-app은 preflight를 거쳐야 돈다 — 동결 조건을 물려받는다."""
    assert re.search(r"^    needs: preflight$", _job("build"), re.M)
    assert re.search(r"^    needs: build$", _job("deploy-db"), re.M)
    assert re.search(r"^    needs: \[build, deploy-db\]$", _job("deploy-app"), re.M)


def test_frozen_run_leaves_a_notice():
    """동결로 건너뛴 실행에는 그 사실을 남기는 잡이 돈다 — 조건이 입구 잡과 정확히 반대다."""
    block = _job("frozen")
    assert _if(block) == "github.event_name == 'push' && vars.DEPLOY_FROZEN == 'true'"
    assert "::notice::" in block
    assert "timeout-minutes:" in block


def test_operations_documents_the_switch():
    """켜고 끄는 자리와 예외 배포 방법이 운영 문서에 있다."""
    text = OPERATIONS.read_text(encoding="utf-8")
    assert "#### 3.1.1 시연 동결" in text
    assert "`DEPLOY_FROZEN` = `true`" in text
    assert "Run workflow" in text
