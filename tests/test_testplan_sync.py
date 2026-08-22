"""이슈 #394 · TEST_PLAN 인벤토리와 실제 테스트 파일의 동기화 검증.

**이 파일이 막으려는 것은 문서가 낡는 것 자체가 아니라, 낡은 것이 보이지 않는 상태다.**

2026-08-15 시점에 ``TEST_PLAN.md``의 파일 참조 정확도는 **24%**였다(실제 61개 중
15개만 일치). 방향 전환으로 들어온 서브시스템 — not under way · YTD 산출 엔진 ·
시뮬레이션 시계 · 운항 상태 — 이 **키워드 검색에서 0건**이었다.

원인은 문서를 안 고쳐서가 아니다. **테스트 파일이 늘어도 문서가 아무 신호를 내지
않았기 때문**이다. ``[ORACLE-M-4]``가 「요약이 실제 행 수와 불일치」를 정정한 뒤에도
같은 일이 재발했다는 것이 그 증거다.

그래서 **파일 목록**을 강제한다. 새 테스트 파일을 만들고 ``§14``에 넣지 않으면
여기서 실패한다.

수치는 강제하지 않았다 (#652에서 추가)
--------------------------------------

파일 목록만 보던 사이 **함수 수 열이 낡았다.** 2026-08-22 하루에만 네 번 어긋났고
방향이 양쪽이었다 — ``test_reports.py``는 문서 33 / 실측 38(**낮음**),
``test_voyage_import_db.py``는 문서 23 / 실측 20(**높음**). 한 번 밀린 것이 아니라
**아무도 보고 있지 않았다**는 뜻이다.

이제 파일별 함수 수와 「합계 N개 파일 · N 함수」를 함께 본다. **수집 수는 보지
않는다** — 파라미터라이즈 때문에 실행해야 알 수 있고, 그 하나를 위해 전 테스트를
수집하면 가드가 본체보다 오래 걸린다.

새 테스트 파일을 추가했다면
--------------------------
``TEST_PLAN.md`` ``§14.2`` 표에 한 행을 넣는다.

.. code-block:: text

    | `test_새파일.py` | <함수 수> | §N 대응 절 |

케이스 하나하나를 옮겨 적을 필요는 없다 — 케이스 규정은 ``§2``~``§7``이 소유하고,
``§14``는 **파일과 절의 대응**만 담는다.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEST_PLAN = _ROOT / "TEST_PLAN.md"
_TESTS_DIR = _ROOT / "tests"

#: ``§14.3`` 계획분 — 규정은 있으나 구현이 아직 없는 테스트.
#: 여기 있는 이름이 실제 파일로 생기면 ``§14.2``로 옮겨야 한다.
PLANNED_ONLY: frozenset[str] = frozenset(
    {
        # 기능③ 연간 시뮬레이션 (#63 · #64)
        "test_annual_simulation_api.py",
        "test_annual_simulation_snapshot.py",
        "test_sensitivity_analysis_api.py",
        # 기상 연동 (#61 · #62)
        "test_weather_factor.py",
        "test_weather_fallback.py",
        # 시나리오 채택 (#58)
        "test_scenario_adopt.py",
        # CSV (#59 · #60)
        "test_csv_security.py",
        # 스냅샷 정책 (#105)
        "test_simulation_policy_filter.py",
        # 성능 벤치마크 (#67)
        "test_benchmarks.py",
        # 소프트 삭제 통합 (#66)
        "test_soft_delete.py",
        # 감사 로그 (#65)
        "test_audit_log.py",
        # 종전 이름 — §14.4가 실제 파일과의 대응을 기록한다
        "test_imo_notation.py",
        "test_error_format.py",
        "test_constraints.py",
        "test_triggers.py",
        "test_immutable_tables.py",
        "test_calculation_query_api.py",
        "test_parameter_import.py",
        "test_voyage_state_transition.py",
    }
)


def _plan_text() -> str:
    return _TEST_PLAN.read_text(encoding="utf-8")


def _actual_test_files() -> set[str]:
    return {p.name for p in _TESTS_DIR.glob("test_*.py")}


#: 테스트 함수를 세는 정규식.
#:
#: **들여쓰기를 포함한다.** ``^def test_``로 세면 클래스 안 메서드가 빠져 887 대 1227로
#: 갈린다 — `#631`에서 실제로 겪었다. ``async def``도 함께 본다.
_TEST_FUNC = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+test_", re.MULTILINE)

#: ``§14.2`` 표의 한 행 — ``| `파일명` | 함수 수 | 설명 |``
_INVENTORY_ROW = re.compile(r"^\| `(test_[a-z0-9_]+\.py)` \| (\d+) \|", re.MULTILINE)

#: ``§14`` 말미의 합계 문장 — ``**합계 98개 파일 · 1261 함수 · 1540 수집.**``
_TOTALS = re.compile(r"\*\*합계 (\d+)개 파일 · ([\d,]+) 함수 · ([\d,]+) 수집\.\*\*")


def _actual_counts() -> dict[str, int]:
    """파일별 실제 테스트 함수 수."""
    return {
        path.name: len(_TEST_FUNC.findall(path.read_text(encoding="utf-8")))
        for path in _TESTS_DIR.glob("test_*.py")
    }


def _documented_counts() -> dict[str, int]:
    """``§14.2`` 표가 적어 둔 파일별 함수 수."""
    return {name: int(count) for name, count in _INVENTORY_ROW.findall(_plan_text())}


def _mentioned_test_files() -> set[str]:
    return set(re.findall(r"test_[a-z0-9_]+\.py", _plan_text()))


def test_every_test_file_is_in_test_plan():
    """실제 테스트 파일이 전부 TEST_PLAN에 등재돼 있다.

    **이 단언이 이 파일의 핵심이다.** 새 파일을 만들고 문서에 넣지 않으면 여기서
    걸린다 — 드리프트가 조용히 쌓이는 경로를 끊는다.
    """
    missing = sorted(_actual_test_files() - _mentioned_test_files())
    assert not missing, (
        f"TEST_PLAN.md §14.2에 없는 테스트 파일 {len(missing)}개: {missing}\n"
        "→ §14.2 표에 `| `파일명` | 함수 수 | 대응 절 |` 행을 추가하세요."
    )


def test_planned_only_files_do_not_exist():
    """계획분으로 적힌 파일이 실제로 생겼으면 §14.2로 옮겨야 한다.

    구현됐는데 계획 목록에 남아 있으면, 그 파일이 어느 절 소관인지가 문서에
    드러나지 않는다.
    """
    now_implemented = sorted(PLANNED_ONLY & _actual_test_files())
    assert not now_implemented, (
        f"계획분이었으나 구현된 파일 {len(now_implemented)}개: {now_implemented}\n"
        "→ TEST_PLAN.md §14.3에서 빼고 §14.2 표로 옮긴 뒤, 이 파일의 "
        "PLANNED_ONLY에서도 제거하세요."
    )


def test_planned_only_entries_are_mentioned_in_plan():
    """계획분 목록과 §14.3이 어긋나지 않는다.

    이 파일에만 적고 문서에 없으면, 문서를 읽는 사람은 그 계획을 모른다.
    """
    plan = _plan_text()
    absent = sorted(name for name in PLANNED_ONLY if name not in plan)
    assert not absent, f"PLANNED_ONLY에 있으나 TEST_PLAN.md에 없는 이름 {len(absent)}개: {absent}"


def test_inventory_section_exists():
    """§14가 존재하고 인벤토리 표를 담고 있다.

    누가 §14를 통째로 지우면 위 단언들이 「전부 없음」으로 무의미해진다 —
    그 경로를 막는다.
    """
    plan = _plan_text()
    assert "## 14. 테스트 파일 인벤토리" in plan
    assert "### 14.2" in plan, "§14.2 구현된 파일 표가 없다"
    assert "### 14.3" in plan, "§14.3 계획분 목록이 없다"


# ---------------------------------------------------------------------------
# 수치 (#652)
#
# 파일 목록만 보던 사이 함수 수 열이 낡았다. 2026-08-22 하루에만 네 번, 방향도
# 양쪽이었다. 수치가 `§14.2` 표에서 파생되므로 **기계적으로 검사할 수 있다.**
# ---------------------------------------------------------------------------


def test_the_counter_finds_methods_inside_classes():
    """세는 방법 자체를 먼저 본다 — 틀리면 아래 단언이 통째로 무의미해진다.

    ``^def test_``로 세면 **클래스 안 메서드가 빠진다.** `#631`에서 887 대 1227로
    갈렸다.
    """
    sample = (
        "def test_top_level():\n"
        "    pass\n"
        "class TestGroup:\n"
        "    def test_method(self):\n"
        "        pass\n"
        "    async def test_async_method(self):\n"
        "        pass\n"
        "# def test_commented_out():\n"
        "def not_a_test():\n"
        "    pass\n"
    )

    assert len(_TEST_FUNC.findall(sample)) == 3


def test_inventory_rows_are_parsed_at_all():
    """표를 읽지 못하면 아래 대조가 「빈 것끼리 같다」로 통과한다."""
    documented = _documented_counts()

    assert len(documented) > 50, f"§14.2 표를 읽지 못했다: {len(documented)}행"
    assert "test_testplan_sync.py" in documented


def test_each_file_count_matches_reality():
    """파일별 함수 수가 실측과 같다.

    **오늘만 네 번 어긋났다.** 방향이 양쪽이라 「한 번 밀렸다」가 아니라 아무도 보고
    있지 않았다는 뜻이다.
    """
    actual = _actual_counts()
    documented = _documented_counts()

    wrong = {
        name: (documented[name], actual[name])
        for name in sorted(documented.keys() & actual.keys())
        if documented[name] != actual[name]
    }
    assert not wrong, "§14.2의 함수 수가 실측과 다릅니다 (문서, 실측):\n" + "\n".join(
        f"  {name}: {doc} → {real}" for name, (doc, real) in wrong.items()
    )


def test_totals_match_reality():
    """「합계 N개 파일 · N 함수」가 실측과 같다.

    **수집 수는 보지 않는다** — 파라미터라이즈 때문에 실행해야 알 수 있고, 그 하나를
    위해 전 테스트를 수집하면 가드가 본체보다 오래 걸린다. 그 값이 손으로 남는 것은
    이 판단의 대가다.
    """
    match = _TOTALS.search(_plan_text())
    assert match, "§14 말미의 합계 문장을 찾지 못했다 — 형식이 바뀌었는지 확인할 것"

    files, funcs = int(match.group(1)), int(match.group(2).replace(",", ""))
    actual = _actual_counts()

    assert files == len(actual), f"파일 수: 문서 {files} / 실측 {len(actual)}"
    assert funcs == sum(actual.values()), f"함수 수: 문서 {funcs} / 실측 {sum(actual.values())}"
