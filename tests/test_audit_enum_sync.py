"""``audit_log.action``·``entity_type`` 값 사슬 드리프트 가드 (`#1343`).

## 무엇이 문제였나

`DB_SCHEMA §2.14`의 두 목록이 **양쪽으로** 어긋나 있었다 — 실제로 쓰는 다섯
(``PASSWORD_CHANGE``·``ACCOUNT_DELETE``·``CHAT_MESSAGE``·``CHAT_TOOL_CALL``·
``PARAMETER_IMPORT``)이 없었고, 한 번도 쓰지 않는 넷(``PARAMETER_CHANGE``·
``VOYAGE_TRANSITION``·``IMPORT``·``EXPORT``)이 적혀 있었다.

이 컬럼에는 집행 CHECK·트리거가 없어(`DB_SCHEMA §7.4`) **DB가 알려 주지 않는다.**
`#1241`(감사 로그 조회 화면)이 이 목록으로 필터를 만들면 **없는 값으로 거르고, 있는
값을 빠뜨린다.**

## 무엇을 검사하나

```
코드가 실제로 쓰는 리터럴  ──==──▶  AUDIT_ACTIONS (+ DB_BACKUP)  ──==──▶  DB_SCHEMA §2.14 행
```

1. **소스에 박힌 리터럴**이 상수 목록과 같다 — 상수만 고치고 코드를 안 고치면(또는 그
   반대) 드러난다
2. `DB_SCHEMA §2.14`의 두 행이 그 집합을 그대로 적는다

`test_weather_source_sync.py`와 같은 틀이다. **뜻(설명)까지는 대조하지 않는다.**
"""

from __future__ import annotations

import re
from pathlib import Path

from cii_platform.db.migration_guard import BACKUP_ACTION
from cii_platform.services.audit import AUDIT_ACTIONS, AUDIT_ENTITY_TYPES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cii_platform"

#: ``action="LOGIN_SUCCESS"`` 꼴. 대문자·밑줄만 쓴다.
_ACTION_LITERAL = re.compile(r'\baction\s*=\s*"([A-Z][A-Z_]*)"')
#: ``entity_type="app_user"`` 꼴.
_ENTITY_LITERAL = re.compile(r'\bentity_type\s*=\s*"([a-z][a-z_]*)"')
#: 문서 행 안의 백틱 값.
_BACKTICKED_UPPER = re.compile(r"`([A-Z][A-Z_]*)`")
_BACKTICKED_LOWER = re.compile(r"`([a-z][a-z_]*)`")


def _sources() -> str:
    """`src/` 전체를 한 문자열로. 값이 어느 파일에 있든 세려는 것이다."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.py")))


def _schema_row(prefix: str) -> str:
    text = (ROOT / "DB_SCHEMA.md").read_text(encoding="utf-8")
    start = text.index("### 2.14")
    section = text[start : text.index("### 2.15", start)]
    return next(line for line in section.split("\n") if line.startswith(prefix))


def test_the_regexes_still_match_something():
    """정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다 — 그것부터 막는다."""
    assert len(AUDIT_ACTIONS) >= 10
    assert len(AUDIT_ENTITY_TYPES) >= 4
    assert len(_ACTION_LITERAL.findall(_sources())) >= 10


def test_action_constants_match_the_literals_in_source():
    """상수 목록이 **코드가 실제로 쓰는 값**과 같다.

    상수만 고치고 호출부를 안 고치면(또는 그 반대) 여기서 드러난다 — 목록이 코드보다
    앞서거나 뒤처지면 `DB_SCHEMA` 대조가 **틀린 기준**으로 통과한다.

    ``DB_BACKUP``은 여기서 빼고 아래에서 따로 본다 — `migration_guard`가 **상수 이름으로**
    넣으므로 ``action="…"`` 리터럴로는 잡히지 않는다.
    """
    written = set(_ACTION_LITERAL.findall(_sources()))

    assert not sorted(written - set(AUDIT_ACTIONS)), (
        f"상수에 없는 action: {sorted(written - set(AUDIT_ACTIONS))}"
    )
    assert not sorted(set(AUDIT_ACTIONS) - written), (
        f"쓰이지 않는 action: {sorted(set(AUDIT_ACTIONS) - written)}"
    )


def test_db_backup_action_is_written_by_the_migration_guard():
    """``DB_BACKUP``은 서비스가 아니라 `migration_guard`가 남긴다 (`#827`).

    마이그레이션 실행 중이라 세션이 다르고, 그래서 :data:`AUDIT_ACTIONS`에 넣지 않는다.
    다만 **`DB_SCHEMA §2.14` 목록에는 있어야 하므로** 그 값이 실제로 기록에 쓰이는지를
    여기서 확인한다 — 쓰이지 않게 되면 문서에서도 빠져야 한다.
    """
    source = (SRC / "db" / "migration_guard.py").read_text(encoding="utf-8")

    assert f'BACKUP_ACTION = "{BACKUP_ACTION}"' in source
    assert '{"action": BACKUP_ACTION}' in source


def test_entity_type_constants_match_the_literals_in_source():
    """``entity_type``도 같은 규칙이다."""
    written = set(_ENTITY_LITERAL.findall(_sources()))

    assert not sorted(written - set(AUDIT_ENTITY_TYPES)), (
        f"상수에 없는 entity_type: {sorted(written - set(AUDIT_ENTITY_TYPES))}"
    )
    assert not sorted(set(AUDIT_ENTITY_TYPES) - written), (
        f"쓰이지 않는 entity_type: {sorted(set(AUDIT_ENTITY_TYPES) - written)}"
    )


def test_db_schema_action_row_matches_the_constants():
    """`DB_SCHEMA §2.14` `action` 행이 상수와 같은 집합을 적는다."""
    documented = set(_BACKTICKED_UPPER.findall(_schema_row("| `action` |")))
    declared = set(AUDIT_ACTIONS) | {BACKUP_ACTION}

    assert not sorted(declared - documented), f"문서에 없는 action: {sorted(declared - documented)}"
    assert not sorted(documented - declared), (
        f"문서에만 있는 action: {sorted(documented - declared)}"
    )


def test_db_schema_entity_type_row_matches_the_constants():
    """`DB_SCHEMA §2.14` `entity_type` 행도 같다."""
    row = _schema_row("| `entity_type` |")
    # 타입·NULL 열의 소문자 낱말이 섞이지 않게 **설명 열만** 본다.
    documented = set(_BACKTICKED_LOWER.findall(row.split("|")[4]))

    assert documented == set(AUDIT_ENTITY_TYPES), (
        f"문서 {sorted(documented)} ↔ 코드 {sorted(AUDIT_ENTITY_TYPES)}"
    )
