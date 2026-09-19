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

리비전을 **하나씩 명시**해야 풀린다 — ``ALLOW_IRREVERSIBLE_DOWNGRADE=057`` (키는 아래
``IRREVERSIBLE``의 ``1c444a5c4819``·``043``·``044``·``057``).
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
#:
#: ⚠️ **CUBRID 전환(`#1058`)으로 마이그레이션 42개가 initial 하나로 합쳐졌다.**
#: 종전에는 리비전마다 무엇을 잃는지 적어 세 분류로 나눴는데, 이제 되돌린다는 것은
#: **스키마 전체를 드롭한다**는 뜻이라 나눌 것이 남지 않는다. 분류가 하나로 준 것은
#: 위험이 줄어서가 아니라 **되돌림의 단위가 커졌기** 때문이다 — 종전에는 `#037` 하나만
#: 내릴 수 있었지만 지금은 전부이거나 아무것도 아니다.
IRREVERSIBLE: dict[str, str] = {
    "1c444a5c4819": (
        "스키마 전체 — 선박·항차·연료 사용량·시나리오·계산 이력·스냅샷·연간 시뮬레이션·"
        "정박 구간·위치 이력·계정·감사 로그까지 24개 테이블을 전부 드롭한다. 다시 "
        "upgrade하면 빈 테이블이 생길 뿐이고, `calculation_run`·`simulation_snapshot`은 "
        "보존 대상이라 되살릴 근거 자체가 없다"
    ),
    # `043`·`044`는 통합 마이그레이션 **밖**이라 따로 내릴 수 있고, 그래서 따로 분류한다
    # (`1c444a5c4819`가 담는 것은 001~042까지다).
    #
    # `043`은 `main`에 있던 항목인데 CUBRID 머지에서 **떨어져 나갔다.** `044`만 살아남아
    # 표가 맞는 것처럼 보였고, CI가 이 브랜치에 붙지 않아 드러나지 않았다. 처음 붙은 CI의
    # `test` 잡이 `KeyError: '043'`으로 잡았다 (`#1058`).
    "043": "fleet_reduction_plan 테이블 — 담당자가 만들어 보고한 감축 계획안 전부",
    # 다시 upgrade하면 전원이 사무직이 된다 — 잠기지는 않지만 누가 현장직이었는지는 사라진다.
    "044": "app_user.role — 사무직·현장직 지정 전부",
    # `057`의 downgrade는 옛 트리거(`OFFICE`·`FIELD`만 허용)를 되돌리기 전에 관리자를
    # 사무직으로 내려야 한다 — 남겨 두면 그 행을 건드리는 다음 UPDATE가 REJECT된다.
    # `044`가 「누가 현장직이었는지」에 대해 가진 것과 같은 성질이다 (#1301).
    "057": (
        "app_user.role의 ADMIN 지정 — 관리자가 전부 사무직으로 내려가고 "
        "누가 관리자였는지가 사라진다"
    ),
}

#: 지워도 되는 일시 데이터 — 사라지면 다시 로그인하거나 메일을 다시 요청하면 된다.
#:
#: 마이그레이션이 하나뿐인 지금은 **비어 있다.** 종전의 `021`(세션)·`034`(토큰)·
#: `041`(대화 기록)은 따로 내릴 수 없고 위 IRREVERSIBLE에 함께 들어간다.
EPHEMERAL: dict[str, str] = {}

#: 다시 upgrade하면 같은 값이 돌아오는 것 — 마이그레이션이 적재하는 규정·시드 값이다.
#: 운영에서 값을 고치는 경로가 생기면(파라미터 import · `#444`) 이 분류를 다시 본다.
#:
#: **한때 비어 있었다(`49d010e`).** CUBRID 전환으로 `017`·`032`가 사라진 상태에 코드를
#: 맞추면서 「시드는 `seed_all()`이 넣으므로 downgrade 대상이 아니다」라고 적었는데,
#: `DB_SCHEMA §8.1.1`은 그렇게 정한 적이 없다 — 「계산에 필요한 seed는
#: `alembic upgrade head` 경로에 들어 있다」가 정본이다. `6c7496c4d122`가 그 경로를
#: 되살렸으므로 분류도 제자리로 돌린다.
REGENERABLE: dict[str, str] = {
    # `031`이 채우던 값이다. CUBRID 전환이 001~042를 합치면서 `017`의 동작(NULL)만
    # 옮기고 `031`을 빠뜨려 8행이 전부 비어 있었다 — `045`가 되살린다 (`#1058`).
    "045": (
        "fuel_type.content_hash 8행 — 다시 upgrade하면 같은 값이 돌아온다"
        "(`DB_SCHEMA §8.3.1`의 산출 규약이 결정론적이다)"
    ),
    "6c7496c4d122": (
        "규제 파라미터 63행(연료 CF 8 · Z-factor 8 · 기준선 20 · d-vector 14 · "
        "기상 계수 10 · 시뮬 3) — "
        "자기가 넣은 키만 지우고, 다시 upgrade하면 같은 값이 돌아온다"
    ),
    # `annual_simulation_run.as_of` 컬럼 — 명시 실행의 기준 시각 기록 (#816 · `052`).
    # 열을 지우는 downgrade는 그 값을 잃지만, 컬럼 자체는 다시 upgrade하면 돌아온다.
    # **값이 재생되지 않는다는 점**은 재현이 그 실행의 `input_hash` 키를 잃는다는
    # 뜻이므로(미명시 실행과 같은 식이 된다) 되돌리기 전에 백업이 필요하다는
    # 가드의 안내를 그대로 받는다.
    "052": "annual_simulation_run.as_of — 컬럼은 재생되지만 저장된 시각 값은 아니므로 백업 뒤에",
    # 대체 연료 선택(#756 ⑴) — 052와 같은 성격. 선택 값이 사라지면 그 실행의
    # `input_hash` 키가 복원되지 않는다.
    "053": "annual_simulation_run.alternative_fuel — 선택 값은 백업 뒤에",
    # 활성-유니크 트리거 교체(#673) — 인덱스·트리거는 다시 upgrade하면 돌아온다.
    # **데이터는 한 행도 바뀌지 않는다.** downgrade는 개정 이행 행이 쌓인 상태에서는
    # UNIQUE 재생성이 실패한다(054 본문의 경고).
    "054": "활성-유니크 트리거 — 구조만 바꾸고 데이터는 무변",
    # vessel.block_coefficient(#966) — 컬럼·트리거 모두 재생 가능. NULL 허용이라
    # 되돌려도 잃는 값은 실측 CB뿐이고, 그것은 선박 제원 화면에서 다시 넣는다.
    "055": "vessel.block_coefficient — 선택 제원이라 값 재입력으로 복구",
    # vessel.call_sign(#1197) — 055와 같은 성격. 컬럼·트리거 모두 재생 가능하고 NULL
    # 허용이라 되돌려도 잃는 값은 호출부호뿐이며, 선박국적증서에 있는 값이라 다시 넣는다.
    "058": "vessel.call_sign — 선택 제원이라 값 재입력으로 복구",
    # voyage.planned_distance_source(#1256) — 컬럼·트리거 모두 재생 가능하고 NULL 허용.
    # 되돌리면 그 사이 저장된 「좌표 추정 · 직접 입력」 표시가 사라지지만, 그 결과는
    # **059 이전과 같은 「모른다」(NULL)**다 — 계산·등급·집계 어디에도 들어가지 않는 표시
    # 값이라 IRREVERSIBLE(막는다)로 둘 성질이 아니다. 052(`as_of`)와 같이 값 자체는
    # 재생되지 않으므로 되돌리기 전에 백업이 필요하다는 가드의 안내를 그대로 받는다.
    "059": "voyage.planned_distance_source — 표시 값이라 사라져도 「모른다」로 돌아갈 뿐",
}


def _allowed() -> set[str]:
    raw = os.environ.get(ALLOW_ENV, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def last_backup_at(bind: Any) -> datetime | None:
    """가장 최근 ``DB_BACKUP`` 감사 기록의 시각. 없으면 ``None``.

    ``bind``는 동기 연결이다 — 마이그레이션 안에서는 ``op.get_bind()``가 준다.
    """
    # `timestamp`와 `action`은 **둘 다 CUBRID 예약어**다 (#1058). 인용하지 않으면
    # `invalid use of timestamp` 구문 오류가 나고, 그 예외가 그대로 올라가
    # **백업이 실제로 있어도** downgrade가 영원히 막힌다 — 막히는 것은 같아 보이지만
    # 이유가 다르고, 정상 경로가 죽는다.
    return bind.execute(
        sa.text('SELECT max("timestamp") FROM audit_log WHERE "action" = :action'),
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
