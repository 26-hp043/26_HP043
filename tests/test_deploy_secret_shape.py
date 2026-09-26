"""배포의 시크릿 모양 진단이 **값을 출력하지 않는다** (`#1634`).

## 무엇을 막는가

PR #1798을 되돌린 원인을 찾으려고 `preflight`에 시크릿의 길이·끝 줄바꿈·특수문자 여부만
찍는 단계를 넣었다. 이 단계가 실수로 값을 찍으면 **GitHub가 가리지 못하는 모양**(일부만,
다른 인코딩으로)으로 운영 비밀번호가 로그에 남는다 — GitHub는 시크릿 원문 전체만 가린다.

그래서 워크플로 안의 스크립트를 **그대로 꺼내 가짜 값으로 실행**하고, 출력에 값의 어떤
토막도 없는지와 끝 줄바꿈을 제대로 세는지를 본다. 가짜 값은 가설의 모양(끝 줄바꿈)과
이스케이프가 갈리는 문자(작은따옴표·큰따옴표·`$`·역슬래시)를 담는다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
STEP = "시크릿 모양 진단 (#1634 · 값은 출력하지 않음)"

#: 가짜 값 — 실제 시크릿이 아니다. 토막이 출력에 새는지 보려고 고유한 문자열을 쓴다.
FAKE = "zq'Wx\"9$HOME\\kp#Lm\n"


def _script() -> str:
    workflow = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["preflight"]["steps"]:
        if step.get("name") == STEP:
            match = re.search(r"python3 - <<'PY'\n(.*?)\nPY", step["run"], re.S)
            assert match, "진단 단계의 파이썬 본문을 찾지 못했다"
            return match.group(1)
    raise AssertionError(f"preflight에 「{STEP}」 단계가 없다")


def _run(env_extra: dict[str, str]) -> str:
    env = {k: v for k, v in os.environ.items() if k not in {"CUBRID_PASSWORD", "SMTP_PASSWORD"}}
    env.update(env_extra)
    done = subprocess.run(
        [sys.executable, "-"], input=_script(), text=True, capture_output=True, env=env, check=True
    )
    return done.stdout


def test_never_prints_the_value() -> None:
    out = _run({"CUBRID_PASSWORD": FAKE})
    core = FAKE.strip()
    # 네 글자 이상의 어떤 토막도 출력에 없어야 한다
    for i in range(len(core) - 3):
        assert core[i : i + 4] not in out, f"값의 토막 {core[i : i + 4]!r}이 출력에 있다"


def test_reports_trailing_newline_and_special_chars() -> None:
    out = _run({"CUBRID_PASSWORD": FAKE})
    line = next(s for s in out.splitlines() if s.startswith("[shape] CUBRID_PASSWORD"))
    assert f"바이트 {len(FAKE.encode())}" in line
    assert "끝 줄바꿈 1개" in line
    for label in ("작은따옴표 예", "큰따옴표 예", "달러 예", "역슬래시 예", "샵 예"):
        assert label in line


def test_empty_secret_is_reported_as_empty() -> None:
    out = _run({"SMTP_PASSWORD": ""})
    assert "[shape] SMTP_PASSWORD: 비어 있음" in out
