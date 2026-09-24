"""CUBRID 데이터 볼륨 안전장치 — 주석과 배포 워크플로 (#1867).

## 무엇을 막는가

종전에는 compose의 명명 볼륨 `cubrid-data`가 엉뚱한 `/var/lib/cubrid`(비어 있다)에
붙어, 실제 데이터가 이미지가 선언한 **익명 볼륨**(`$CUBRID_DATABASES` =
`/home/cubrid/CUBRID/databases`)에 쌓였다. `docker compose down`은 `-v` 없이도 다음
`up`에서 새 익명 볼륨을 만들어 빈 DB로 뜨게 했다(2026-09-24 로컬 실측). 이제
`cubrid-data`를 이미지의 데이터 경로에 붙인다 — 다만 옛 익명 볼륨에 데이터가 있는
호스트에서 처음 적용하면 빈 `cubrid-data`가 그 데이터를 가린다(2026-09-25 리허설).

## 이 파일이 잠그는 것

1. 두 compose 파일의 CUBRID 서비스가 `cubrid-data`를 **이미지의 데이터 경로**에
   붙이는가, 그 줄 근처에 옮기는 절차를 가리키는 주석이 있는가.
2. `deploy.yml`의 db-01 단계가 `up -d` **전에** 「데이터가 익명 볼륨에 있고
   `cubrid-data`는 비었다」를 보고 멈추는가 — 옮기는 절차를 건너뛴 첫 배포가 운영
   데이터를 가리지 않게.
3. `deploy.yml`의 db-01 단계가 `docker compose … down`을 **`FORCE_DB_INIT` 분기
   밖에서** 쓰지 않는가 — 밖에서 쓰면 평소 배포(재생성 경로, `pull` + `up -d`)마다
   컨테이너가 내려갔다 올라오며 새 익명 볼륨을 만들어 데이터를 지운다.

DB 없이 파일만 읽어 확인한다 — `test_deploy_sha_pinning.py`와 같은 근거로, 배포
워크플로는 실제로 돌려 재현할 수 없고 실행하면 운영 서버를 건드린다.

케이스: 없음 (컴포즈·워크플로 배선 가드라 `TEST_PLAN §2`~`§7`의 케이스 체계 밖이다)
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_DEV = _ROOT / "docker-compose.yml"
_COMPOSE_PROD_DB = _ROOT / "docker-compose.prod.db.yml"
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"

#: 위험 주석이 반드시 담아야 하는 핵심어 — 어느 하나라도 없으면 "왜 위험한지"가
#: 사라진 채 형식만 남은 주석이 될 수 있다.
_WARNING_MARKERS = ("익명 볼륨", "#1867", "§9.2.1")

#: 이미지 ``cubrid/cubrid:11.4``가 ``VOLUME``으로 선언한 데이터 경로(= ``$CUBRID_DATABASES``).
#: ``docker image inspect cubrid/cubrid:11.4`` → ``{"/home/cubrid/CUBRID/databases":{}}``(실측).
#: 이미지를 판올림해 경로가 바뀌면 이 값과 두 compose 파일을 함께 고친다.
_IMAGE_DATA_PATH = "/home/cubrid/CUBRID/databases"

#: 주석을 찾는 창 — 마운트 줄 바로 위 몇 줄 안에 있어야 "근처"로 친다.
_WINDOW = 8


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _find_cubrid_data_mount_line(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if re.search(r"cubrid-data:\s*/", line):
            return i
    raise AssertionError("`cubrid-data:` 마운트 줄을 찾지 못했다 — 파일이 바뀌었는지 확인할 것")


def _mount_target(line: str) -> str:
    match = re.search(r"cubrid-data:\s*(/[^\s\]\"',]+)", line)
    assert match, line
    return match.group(1)


def _warning_near(lines: list[str], target_index: int) -> bool:
    # 주석은 마운트 줄 위에도 아래에도 둘 수 있다 — 양쪽 창을 본다.
    start = max(0, target_index - _WINDOW)
    nearby = "\n".join(lines[start : target_index + _WINDOW + 1])
    return all(marker in nearby for marker in _WARNING_MARKERS)


def test_dev_compose_cubrid_mount_has_volume_warning():
    """`docker-compose.yml`의 `cubrid-data` 마운트 근처에 익명 볼륨 위험 주석이 있다."""
    lines = _lines(_COMPOSE_DEV)
    idx = _find_cubrid_data_mount_line(lines)
    assert _warning_near(lines, idx), (
        f"docker-compose.yml:{idx + 1} 근처 {_WINDOW}줄 안에 "
        f"익명 볼륨 위험 주석({_WARNING_MARKERS})이 없다"
    )


def test_prod_db_compose_cubrid_mount_has_volume_warning():
    """`docker-compose.prod.db.yml`의 `cubrid-data` 마운트 근처에 같은 주석이 있다."""
    lines = _lines(_COMPOSE_PROD_DB)
    idx = _find_cubrid_data_mount_line(lines)
    assert _warning_near(lines, idx), (
        f"docker-compose.prod.db.yml:{idx + 1} 근처 {_WINDOW}줄 안에 "
        f"익명 볼륨 위험 주석({_WARNING_MARKERS})이 없다"
    )


def _db01_run_block(body: str) -> str:
    """`db-01 스택 적용` 단계의 heredoc 본문만 잘라낸다."""
    marker = "db-01 스택 적용"
    start = body.index(marker)
    heredoc_start = body.index("<<'ENDSSH'", start) + len("<<'ENDSSH'")
    heredoc_end = body.index("\n          ENDSSH", heredoc_start)
    return body[heredoc_start:heredoc_end]


def test_db01_step_is_found_and_read():
    """앞으로의 검사가 빈 문자열을 훑어 조용히 통과하지 않도록 먼저 확인한다."""
    block = _db01_run_block(_DEPLOY.read_text(encoding="utf-8"))
    assert "docker compose -f docker-compose.prod.db.yml up -d" in block


def _unguarded_downs(block: str) -> list[str]:
    """`FORCE_DB_INIT` 조건이 열려 있지 않은 자리의 `docker compose … down` 줄.

    **모든** `if`를 스택에 넣는다 — `[` 없는 조건(`if docker compose …; then`)도
    같은 `fi`로 닫히므로, `if [`만 넣고 `fi`마다 빼면 가드가 먼저 빠져 정당한
    `down -v`를 가드 밖으로 잘못 읽는다(PR #1875 리뷰). 한 줄에 `fi`까지 닫힌 `if`는
    넣지 않는다.
    """
    guard_stack: list[bool] = []
    offending: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if re.match(r"if\s", stripped) and not re.search(r"(;|\s)fi\s*$", stripped):
            guard_stack.append("FORCE_DB_INIT" in stripped)
        elif stripped == "fi" or stripped.startswith("fi "):
            if guard_stack:
                guard_stack.pop()
        elif re.search(r"docker compose .*\bdown\b", stripped) and not any(guard_stack):
            offending.append(stripped)
    return offending


def test_guard_tracking_counts_bracketless_ifs():
    """`[` 없는 `if`가 가드 안에 끼어도 가드 안의 `down -v`를 밖으로 읽지 않는다."""
    inside = (
        'if [ "${FORCE_DB_INIT}" = "true" ]; then\n'
        "  if docker compose -f x.yml exec -T cubrid true; then\n"
        "    echo ok\n"
        "  fi\n"
        "  docker compose -f docker-compose.prod.db.yml down -v\n"
        "fi\n"
    )
    assert _unguarded_downs(inside) == []
    outside = inside + "docker compose -f docker-compose.prod.db.yml down\n"
    assert _unguarded_downs(outside) == ["docker compose -f docker-compose.prod.db.yml down"]


def test_down_only_appears_inside_force_db_init_guard():
    """`docker compose … down`은 `FORCE_DB_INIT` 분기 안에서만 쓰인다.

    분기 밖에서 쓰면 **평소 배포**(재생성 경로)마다 컨테이너가 내려갔다 올라오며
    새 익명 볼륨을 만들어 데이터를 지운다 — `force_db_init`을 켜지 않아도 매
    배포가 파괴적이게 된다. if/fi 중첩을 스택으로 추적해, `down`을 만나는 시점에
    스택 어딘가(중첩 바깥 포함)에 `FORCE_DB_INIT` 조건이 열려 있는지 본다.
    """
    offending = _unguarded_downs(_db01_run_block(_DEPLOY.read_text(encoding="utf-8")))
    assert offending == [], (
        "`FORCE_DB_INIT` 분기 밖에서 `docker compose … down`을 쓴다:\n  " + "\n  ".join(offending)
    )


def test_force_db_init_guard_still_uses_down_dash_v():
    """가드 자체가 사라져 위 검사가 공허하게 통과하지 않는지 — `down -v`가 실재한다."""
    block = _db01_run_block(_DEPLOY.read_text(encoding="utf-8"))
    assert re.search(r'if \[ "\$\{FORCE_DB_INIT\}" = "true" \]; then', block)
    assert "docker compose -f docker-compose.prod.db.yml down -v" in block


def test_both_compose_files_mount_cubrid_data_at_the_image_data_path():
    """`cubrid-data`가 이미지의 데이터 경로에 붙는다 — 종전 `/var/lib/cubrid`는 비어 있었다."""
    for path in (_COMPOSE_DEV, _COMPOSE_PROD_DB):
        lines = _lines(path)
        target = _mount_target(lines[_find_cubrid_data_mount_line(lines)])
        assert target == _IMAGE_DATA_PATH, f"{path.name}: cubrid-data가 {target}에 붙는다"


def test_db01_step_stops_before_up_when_data_is_still_in_an_anonymous_volume():
    """db-01 단계가 `up -d` **전에** 익명 볼륨 · 빈 `cubrid-data`를 보고 멈춘다.

    마운트를 옮긴 첫 배포에서 옮기는 절차(OPERATIONS §9.2.1)를 건너뛰면 `up -d`가 빈
    볼륨을 데이터 경로에 붙인다. 검사가 `up -d` 뒤에 있으면 이미 늦다 — 순서까지 본다.
    검사가 같은 compose 프로젝트의 볼륨만 보는지도 본다(같은 호스트의 ourtax 스택).
    """
    block = _db01_run_block(_DEPLOY.read_text(encoding="utf-8"))
    check = block.index(f'{{{{if eq .Destination "{_IMAGE_DATA_PATH}"}}}}')
    up = block.index("docker compose -f docker-compose.prod.db.yml up -d")
    assert check < up, "사전 검사가 up -d 뒤에 있다"
    guard = block[check:up]
    assert "exit 1" in guard
    assert "com.docker.compose.project=" in guard
    assert "test -d /v/cii" in guard
