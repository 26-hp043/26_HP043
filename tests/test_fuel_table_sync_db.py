"""연료 CF 표 ↔ 시드 (`#773` · IT-FUEL-007~009).

## 왜 필요한가

``PRD §3.4.2``가 연료 코드와 CF를 정한다. 그 표와 ``fuel_type`` 시드가 갈리면
**화면의 연료 선택지와 정본이 다른 말을 한다** — 그리고 그것은 화면을 깨뜨리지
않으므로 발견되지 않는다.

⚠️ **이 표에는 알려진 공백이 있다.** `#87` 검토가 찾아 `#773`이 판정을 기다린다.

===========  =========================================================
 ``Ethane``   **원문 표에는 있고 정본 표에는 없다.** 원문은 CF가 9개인데
              우리는 8개다(팀원 회신 `#87` · 값 인쇄처 `MEPC.364(79)`)
 ``OTHER``    **정본 표에는 있고 시드에는 없다.** CF가 사용자 입력이라
              고정 시드 행으로 둘 수 없다(`#83`이 판정)
===========  =========================================================

앞엣것은 **정본 ↔ 원문**이라 여기서 볼 수 없다(원문이 기계가 읽을 형태가 아니다) —
`PRD §3.4.2` 각주가 그 사실을 적는다. 뒤엣것은 **정본 ↔ 시드**라 여기서 본다.

## 값을 정하지 않는다

이 검사는 **공백을 붙잡기만** 한다. `Ethane`을 넣을지는 `AGENTS §2.1`상 팀원
확인을 거친 판정 사항이고, 지어낸 규제값은 **틀렸다는 사실이 화면에 드러나지
않는다**(`#834`와 같은 판단).
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text

_PRD = Path(__file__).resolve().parents[1] / "PRD.md"

#: 정본 표에는 있고 시드에는 없는 코드 — **사유와 함께** 적는다.
#:
#: ⚠️ 시드에 들어가면 이 항목을 지워야 한다. 남겨 두면 검사가 거짓말한다.
KNOWN_NOT_SEEDED: dict[str, str] = {
    "OTHER": "CF가 사용자 입력이라 고정 시드 행으로 둘 수 없다 — 포함 여부는 #83",
}

#: `PRD §3.4.2` 표 행 — ``| CODE | 표시명 | CF | MVP |``
_ROW = re.compile(r"^\|\s*([A-Z][A-Z_]+)\s*\|[^|]*\|\s*([0-9.]+|사용자 입력)\s*\|", re.M)


def _prd_fuels() -> dict[str, str]:
    body = _PRD.read_text(encoding="utf-8").split("#### 3.4.2", 1)[1].split("#### 3.4.3", 1)[0]
    return {code: cf for code, cf in _ROW.findall(body)}


async def test_prd_table_is_readable(conn):
    """IT-FUEL-007 — 정본 표를 읽을 수 있다.

    표 형식이 바뀌면 아래 두 검사가 **0건을 대조하고 통과**한다 — `#634`에서
    실제로 그럴 뻔했다. 먼저 읽혔는지부터 본다.
    """
    fuels = _prd_fuels()
    assert len(fuels) >= 8, fuels
    assert fuels["HFO"] == "3.114", fuels.get("HFO")


async def test_seed_codes_match_the_prd_table(conn):
    """IT-FUEL-008 — 시드 코드가 정본 표와 **정확히 같다**(알려진 공백 제외).

    양방향으로 깨진다.

    ===================  ==========================================
     시드에만 있다          정본에 없는 연료를 화면이 고르게 한다
     정본에만 있다          목록에 없으면 **사유가 있어야 한다**
    ===================  ==========================================
    """
    seeded = {row[0] for row in await conn.execute(text("SELECT code FROM fuel_type"))}
    in_prd = set(_prd_fuels())

    extra = seeded - in_prd
    assert not extra, f"정본 표에 없는 시드 코드: {sorted(extra)}"

    missing = in_prd - seeded
    assert missing == set(KNOWN_NOT_SEEDED), (
        f"실측 {sorted(missing)} ≠ 목록 {sorted(KNOWN_NOT_SEEDED)} — "
        "새 공백이면 사유와 함께 목록에 넣고, 시드에 들어갔으면 목록에서 뺄 것"
    )


async def test_seeded_cf_values_match_the_prd_table(conn):
    """IT-FUEL-009 — ⚠️ **CF 값이 정본과 같다**.

    코드만 맞고 값이 갈리면 **계산이 조용히 틀린다** — CF는 CII의 분자를 만드는
    값이라, 0.1만 달라도 등급이 바뀔 수 있다. 그런데 화면은 그대로 뜬다.
    """
    prd = _prd_fuels()
    rows = await conn.execute(text("SELECT code, cf FROM fuel_type ORDER BY code"))
    mismatched = [
        (code, str(cf), prd[code])
        for code, cf in rows
        if code in prd and float(cf) != float(prd[code])
    ]
    assert not mismatched, f"CF가 정본과 다르다 (코드, 시드, 정본): {mismatched}"


async def test_every_known_gap_carries_a_reason(conn):
    """IT-FUEL-010 — 목록의 항목마다 **사유와 이슈 번호**가 있다.

    「TODO」로 채우면 목록이 그저 통과용이 된다(`#834`와 같은 규칙).
    """
    for code, reason in KNOWN_NOT_SEEDED.items():
        assert len(reason) >= 20, (code, reason)
        assert "#" in reason, f"{code}: 이슈 번호가 없다"
