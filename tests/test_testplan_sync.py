"""이슈 #394 · TEST_PLAN 인벤토리와 실제 테스트 파일의 동기화 검증.

**이 파일이 막으려는 것은 문서가 낡는 것 자체가 아니라, 낡은 것이 보이지 않는 상태다.**

2026-08-15 시점에 ``TEST_PLAN.md``의 파일 참조 정확도는 **24%**였다(실제 61개 중
15개만 일치). 방향 전환으로 들어온 서브시스템 — not under way · YTD 산출 엔진 ·
시뮬레이션 시계 · 운항 상태 — 이 **키워드 검색에서 0건**이었다.

원인은 문서를 안 고쳐서가 아니다. **테스트 파일이 늘어도 문서가 아무 신호를 내지
않았기 때문**이다. ``[ORACLE-M-4]``가 「요약이 실제 행 수와 불일치」를 정정한 뒤에도
같은 일이 재발했다는 것이 그 증거다.

그래서 수치가 아니라 **파일 목록**을 강제한다. 새 테스트 파일을 만들고 ``§14``에
넣지 않으면 여기서 실패한다.

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
