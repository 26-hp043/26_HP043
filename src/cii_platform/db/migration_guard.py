"""되돌릴 수 없는 downgrade를 프로덕션에서 막는다 (``DB_SCHEMA §8.1.2``, #819).

## 무엇을 막는가

``downgrade()``가 **운영 데이터를 지우고, 다시 ``upgrade``해도 그 값을 되살릴 수 없는**
리비전이다. 둘 중 하나다.

- **테이블·행을 지운다** — 선박·항차·계산 이력처럼 사용자가 쌓은 데이터. 다시
  ``upgrade``하면 빈 테이블이 생길 뿐이다
- **보존 대상 테이블의 열을 지운다** — ``simulation_snapshot``·``calculation_run``은
  UPDATE가 트리거로 막혀 있어(``DB_SCHEMA §7.3 [X-2]``) 다시 ``upgrade``해 열이 생겨도
  **기존 행을 채울 방법이 없다.** 037을 되돌렸다 올리면 과거 연간 시뮬레이션이 전부
  재현 불가가 된다

배포 후 롤백은 정상 운영 절차인데, 그 절차 안에 이런 리비전이 섞여 있으면 **한 번의
롤백이 복구 불가능한 손실**이 된다. 경고 문구만으로는 부족해 막는다(2026-09-08 판정).

## 어떻게 푸는가

리비전을 **하나씩 명시**해야 풀린다 — ``ALLOW_IRREVERSIBLE_DOWNGRADE=037,016``.
「전부 허용」 스위치를 두지 않는 것은 그 스위치가 켜진 채로 남으면 다음 롤백에서 같은
손실이 조용히 재현되기 때문이다.

**명시만으로는 풀리지 않는다 — 24시간 안의 백업 기록이 함께 있어야 한다** (#827 ·
2026-09-11 결정 2-⑤ 「#827 백업과 연계」). 백업 스크립트(``scripts/db_backup.py``)는 덤프를
검증한 뒤 ``audit_log``에 ``DB_BACKUP`` 행을 남기고, 가드는 **마이그레이션이 쓰는 그
연결로** 그 행을 찾는다. 파일이 아니라 DB에서 찾는 이유 — 마이그레이션은 앱 컨테이너에서
돌고 덤프는 호스트에 떨어져, 파일 경로로는 서로를 볼 수 없다. 종전(#819)에는 「백업을 뜬
뒤」가 오류 문구에만 있어, 명시 한 번으로 백업 없이 지울 수 있었다.

개발·테스트 환경에서는 막지 않는다. ``tests/test_zz_roundtrip.py``가 ``downgrade base``를
돌려 모든 ``downgrade()``가 실행 가능한지 검증하므로, 막으면 그 검증이 사라진다.

## 목록을 여기 두는 이유

손실 설명이 마이그레이션 파일마다 흩어지면 **새 마이그레이션이 분류를 빠뜨려도** 알 수
없다. ``tests/test_migration_guard.py``가 파괴적 연산을 가진 모든 ``downgrade()``가 아래
세 목록 중 하나에 들어 있는지 검사한다 — ``#775``(다중 회사)처럼 큰 마이그레이션이 올
때 분류를 강제한다.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from cii_platform.config import is_production

_log = logging.getLogger(__name__)

#: 해제 환경변수. 값은 쉼표로 구분한 리비전 목록이다.
ALLOW_ENV = "ALLOW_IRREVERSIBLE_DOWNGRADE"

#: 백업 스크립트가 남기는 감사 로그 ``action`` (``DB_SCHEMA §2.14`` · #827).
#: ``scripts/db_backup.py``의 같은 이름 상수와 같아야 한다 — 검사가 대조한다.
BACKUP_ACTION = "DB_BACKUP"

#: 해제에 쓸 수 있는 백업의 최대 나이. 하루 한 번 백업(``scripts/db_backup.py`` 기본 주기)이면
#: 언제 롤백하든 마지막 정기 백업이 이 안에 든다 — 그래도 **롤백 직전에 한 번 더 뜨는 것**이
#: 절차다(``DB_SCHEMA §8.1.2``). 그 사이에 쌓인 데이터는 정기 백업에 없다.
BACKUP_MAX_AGE = timedelta(hours=24)

#: 되돌리면 운영 데이터가 복구 불가능하게 사라지는 리비전 → 무엇이 사라지는가.
IRREVERSIBLE: dict[str, str] = {
    "003": "vessel 테이블 — 등록된 선박 전부",
    "005": "voyage 테이블 — 항차 이력 전부",
    "006": "voyage_fuel_use 테이블 — 항차별 연료 사용량·CF 스냅샷 전부",
    "007": "voyage_scenario 테이블 — 저장된 시나리오 비교 전부",
    "008": "calculation_run 테이블 — 보존 대상 계산 이력 전부",
    "009": "simulation_snapshot 테이블 — 보존 대상 스냅샷 전부",
    "013": "weather_snapshot 테이블 — 계산에 쓴 기상 데이터 기록 전부",
    "014": "annual_simulation_run 테이블 — 연간 시뮬레이션 실행 이력 전부",
    "015": "audit_log 테이블 — 감사 로그 전부",
    "016": (
        "calculation_run.weather_snapshot_id — 보존 대상 테이블이라 다시 upgrade해도 "
        "기존 행을 채울 수 없다"
    ),
    "020": "app_user 테이블 — 계정 전부",
    "024": (
        "calculation_run.needs_recalc — 어느 계산이 재계산 대상이었는지가 사라진다"
        "(보존 대상 테이블이라 다시 표시할 근거도 없다)"
    ),
    "025": "not_underway_period·not_underway_fuel_use 테이블 — 정박·묘박 기록 전부",
    "026": "vessel의 위치·운항 상태 5개 열 — 선박별 현재 위치·상태",
    "028": "not_underway_period.distance_nm — 정박 구간 이동 거리",
    "030": "not_underway_fuel_use.cf_used — 기록 시점의 CF 스냅샷",
    "033": "app_user 행 전부(DELETE)와 비밀번호 해시 — 계정을 다시 만들 근거가 없다",
    "037": (
        "simulation_snapshot.vessel_json — 보존 대상 테이블이라 다시 upgrade해도 기존 "
        "행을 채울 수 없고, 과거 연간 시뮬레이션이 전부 재현 불가가 된다"
    ),
    # 지나간 시각의 좌표는 되살릴 방법이 없다. AIS는 재조회로 과거를 주지 않고
    # (aisstream.io는 끊긴 구간 복구가 없다), 사람이 넣은 위치는 애초에 재현 불가다.
    "040": "vessel_position_snapshot 테이블 — 수집한 위치 이력 전부",
}

#: 지워도 되는 일시 데이터 — 사라지면 다시 로그인하거나 메일을 다시 요청하면 된다.
EPHEMERAL: dict[str, str] = {
    "021": "user_session — 로그인 세션. 사라지면 전원 다시 로그인한다",
    "034": "user_token — 인증·재설정 링크. 사라지면 메일을 다시 요청한다",
    # 90일 뒤 어차피 지워지는 대화 기록이다(`PRD §16.3` 채팅 보존 정책). 계산
    # 원본은 `calculation_run`에 따로 있고 챗봇 로그는 가리키기만 한다 (`#120`).
    "041": "chat_session·chat_message — 90일 보존 대화 기록. 계산 원본은 남는다",
}

#: 다시 upgrade하면 같은 값이 돌아오는 것 — 마이그레이션이 적재하는 규정·시드 값이다.
#: 운영에서 값을 고치는 경로가 생기면(파라미터 import · `#444`) 이 분류를 다시 본다.
REGENERABLE: dict[str, str] = {
    "001": "pg_trgm 확장·공용 트리거 함수 — 데이터가 없다",
    "002": "fuel_type — 017이 다시 적재한다",
    "004": "regulation_year — 032가 다시 적재한다",
    "010": "cii_reference_line — 032가 다시 적재한다",
    "011": "cii_rating_boundary — 032가 다시 적재한다",
    "012": "weather_model_parameter — 019가 다시 적재한다",
    "017": "fuel_type 시드 — 자기가 넣은 키만 지운다",
    "019": "weather_model_parameter 시드 — 자기가 넣은 키만 지운다",
    "022": "app_user updated_at 트리거 — 데이터가 없다",
    "023": "CHECK 제약·인덱스 — 데이터가 없다",
    "031": "fuel_type.content_hash — 다시 upgrade하면 같은 규약으로 다시 계산한다",
    "032": "규제 파라미터 시드 — 자기가 넣은 키만 지운다",
    "035": "simulation_parameter — 035가 다시 적재한다",
    # 캐시라 잃는 것이 없다 — 다시 물으면 다시 채워진다. 항차에는 좌표 **값이 복사돼**
    # 들어가므로(FK 없음) 이 표를 비워도 항차는 온전하다 (`#768` · `DB_SCHEMA §2.20`).
    "039": "port_geocode — 항만명 좌표 조회 캐시. 다시 조회하면 채워진다",
}


def _allowed() -> set[str]:
    raw = os.environ.get(ALLOW_ENV, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def last_backup_at(bind: Any) -> datetime | None:
    """가장 최근 ``DB_BACKUP`` 감사 기록의 시각. 없으면 ``None``.

    ``bind``는 동기 연결이다 — 마이그레이션 안에서는 ``op.get_bind()``가 준다.
    """
    return bind.execute(
        sa.text("SELECT max(timestamp) FROM audit_log WHERE action = :action"),
        {"action": BACKUP_ACTION},
    ).scalar()


def _migration_bind() -> Any:
    """지금 돌고 있는 마이그레이션의 연결. 마이그레이션 밖에서 부르면 alembic이 던진다."""
    from alembic import op

    return op.get_bind()


def _require_recent_backup(revision: str) -> None:
    last = last_backup_at(_migration_bind())
    if last is not None and datetime.now(UTC) - last <= BACKUP_MAX_AGE:
        return
    seen = "백업 기록이 없습니다" if last is None else f"마지막 백업이 {last.isoformat()}입니다"
    hours = int(BACKUP_MAX_AGE.total_seconds() // 3600)
    raise RuntimeError(
        f"리비전 {revision}의 downgrade는 {ALLOW_ENV}로 명시했지만 {hours}시간 안의 "
        f"백업이 없어 막았습니다 — {seen}. "
        "먼저 `python3 scripts/db_backup.py backup`으로 백업을 뜨고 다시 실행하십시오 "
        "(#827 · DB_SCHEMA §8.1.2)."
    )


def guard_irreversible_downgrade(revision: str) -> None:
    """프로덕션에서 ``revision``의 downgrade를 막는다.

    풀리는 조건은 둘 다다 — ``ALLOW_IRREVERSIBLE_DOWNGRADE``에 이 리비전이 있고, **24시간
    안의 백업 기록**이 있다(#827). 둘 다 맞으면 경고만 남기고 지나간다.

    각 리비전의 ``downgrade()`` **맨 앞**에서 부른다 — 무엇이든 지우기 전에 끊어야 한다.
    PostgreSQL은 DDL도 트랜잭션이라 여러 리비전을 한 번에 내릴 때 뒤에서 끊겨도 앞의
    것이 함께 되돌려지지만, 그것에 기대지 않는다.
    """
    loss = IRREVERSIBLE[revision]
    if not is_production():
        return
    if revision not in _allowed():
        raise RuntimeError(
            f"리비전 {revision}의 downgrade는 프로덕션에서 막혀 있습니다 — {loss}. "
            f"백업을 뜬 뒤(`python3 scripts/db_backup.py backup` · #827) "
            f"{ALLOW_ENV}={revision} 로 이 리비전을 명시해 해제하십시오 "
            "(DB_SCHEMA §8.1.2)."
        )
    _require_recent_backup(revision)
    _log.warning(
        "되돌릴 수 없는 downgrade를 해제 상태로 실행합니다 — %s: %s (%s=%s)",
        revision,
        loss,
        ALLOW_ENV,
        os.environ.get(ALLOW_ENV, ""),
    )
