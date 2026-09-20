"""`README` 배포 절이 실제 운영·코드와 갈리지 않게 한다 (`#1339`).

## 무엇이 문제였나

`README`의 「배포」 절이 **단일 호스트 `docker-compose.prod.yml` + nginx 리버스
프록시**만 설명하면서 *「그래서 백엔드에 CORS 설정이 없다」*고 적었다. 실제 운영은
**OCI 2-VM 분리 + Cloudflare Pages**이고, `api/main.py`가 `CORS_ALLOW_ORIGINS`를 읽어
`CORSMiddleware`를 붙인다 — **그 값이 없으면 화면이 API를 부르지 못한다.**

배포 절차를 `README`에서 읽고 시작한 사람은 **없는 구성**을 세우게 된다.

## 무엇을 검사하나

문장을 통째로 묶지 않는다(`AGENTS §4.6` — 표시 문구는 성질로 단언한다). 두 가지만 본다.

1. 「CORS 설정이 없다」류의 **사실과 다른 단정**이 남아 있지 않다
2. 배포 절이 **운영 정본(`docs/OPERATIONS.md`)과 분리 토폴로지 compose 파일**을 가리킨다
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _deploy_section() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## 배포")
    return text[start : text.index("\n## ", start + 1)]


def test_the_section_is_found_at_all():
    """절을 못 찾으면 아래 검사가 「빈 문자열에 없다」로 조용히 통과한다."""
    assert len(_deploy_section()) > 1000


def test_it_does_not_claim_there_is_no_cors():
    """**「CORS 설정이 없다」는 사실이 아니다** (`#1339`).

    `api/main.py`가 `CORS_ALLOW_ORIGINS`를 읽어 미들웨어를 붙인다 — 미설정일 때만
    붙이지 않는다. 운영(Cloudflare Pages)은 크로스 오리진이라 **그 값이 필수**다.
    """
    section = _deploy_section()
    # ⚠️ 부정문이 실제로 남아 있는지를 본다. 정정 각주에서 인용하는 형태
    # (「…는 사실이 아니다」)는 걸러 내야 하므로 **인용부호 밖의 단정**만 찾는다.
    offenders = [
        line
        for line in section.split("\n")
        if "CORS 설정이 없다" in line and "사실이 아니다" not in line
    ]
    assert not offenders, f"사실과 다른 단정이 남아 있다: {offenders}"


def test_it_points_at_the_operations_runbook_and_the_split_topology():
    """배포 절이 **운영 정본과 실제 토폴로지**를 가리킨다 (`#1339`)."""
    section = _deploy_section()

    assert "docs/OPERATIONS.md" in section, "운영 정본을 가리키지 않는다"
    for name in ("docker-compose.prod.app.yml", "docker-compose.prod.db.yml"):
        assert name in section, f"분리 토폴로지 compose({name})를 언급하지 않는다"
    assert "CORS_ALLOW_ORIGINS" in section, "운영에 필요한 환경변수를 말하지 않는다"


def test_the_compose_files_it_names_exist():
    """가리키는 파일이 **실재한다** — 이름만 적혀 있고 없으면 더 나쁘다."""
    section = _deploy_section()
    for name in (
        "docker-compose.prod.yml",
        "docker-compose.prod.app.yml",
        "docker-compose.prod.db.yml",
    ):
        assert name in section
        assert (ROOT / name).exists(), f"{name}이 저장소에 없다"
