"""`docs/OPERATIONS.md`의 Pages 배포 명령이 현행 구성과 같다 (`#1669`).

종전 수동 배포 절(`§3.2` · `§6.2`)은 **별도 백엔드 오리진**(`VITE_API_BASE_URL=http://<IP>…`)과
**위치 인자 `dist`**(`wrangler pages deploy dist --project-name bluelog`)를 안내했다. 앞의 것은
교차 사이트 쿠키가 실리지 않던 구성이고(`#1322`), 뒤의 것은 `frontend/wrangler.toml`의
`pages_build_output_dir`와 충돌해 wrangler가 거부한다(`deploy.yml` 주석). 자동 배포는 이미
바뀌었는데 문서만 남아, 급할 때 문서대로 하면 다른 결과가 나왔다.

**코드 블록만 본다** — 본문에는 「종전에는 …이었다」 같은 역사 기록이 남아 있어야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1] / "docs" / "OPERATIONS.md"


def _code_lines() -> list[str]:
    text = _OPS.read_text(encoding="utf-8")
    blocks = re.findall(r"^```[a-z]*\n(.*?)^```", text, re.M | re.S)
    return [line for block in blocks for line in block.splitlines()]


def test_build_commands_use_the_same_origin_path():
    """빌드 명령의 `VITE_API_BASE_URL`은 상대 경로 `/api/v1`뿐이다 — 같은 오리진(`#1322`)."""
    values = [
        m.group(1) for line in _code_lines() for m in re.finditer(r"VITE_API_BASE_URL=(\S+)", line)
    ]
    assert values, "빌드 명령이 코드 블록에서 사라졌다면 이 검사도 함께 고친다"
    assert set(values) == {"/api/v1"}, values


def test_pages_deploy_takes_no_positional_directory():
    """`wrangler pages deploy`에 위치 인자를 주지 않는다 — 디렉터리·이름은 `wrangler.toml`에."""
    deploys = [line for line in _code_lines() if "pages deploy" in line]
    assert deploys, "배포 명령이 코드 블록에서 사라졌다"
    for line in deploys:
        after = line.split("pages deploy", 1)[1].split()
        assert not after or after[0].startswith("-"), line
        assert "--project-name" not in line, line
