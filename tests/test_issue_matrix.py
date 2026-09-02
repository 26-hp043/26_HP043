"""이슈 매트릭스 집계 (#93).

**네트워크를 타지 않는다.** `summarize`·`render`는 이미 읽어 온 목록만 받는다 —
`gh`를 부르는 자리는 `fetch` 하나이며 그것은 여기서 보지 않는다.

여기서 잠그는 것은 셋이다.

1. **라벨이 없는 이슈가 표에서 사라지지 않는다** — `#93`이 08-22에 겪은 상태다.
   라벨을 빠뜨린 이슈가 표에서 빠지면 「없는 것」이 된다
2. **합계가 열린 이슈 수와 같다** — 레이어를 둘 붙인 이슈를 두 번 세면 합계가
   맞지 않고, 그 차이를 설명할 수 없다
3. **레이어 정의가 `#93` 본문과 같다** — 라벨이 늘면 표에 새 줄이 생겨야 한다
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from issue_matrix import LAYERS, UNLABELED, layer_of, render, summarize  # noqa: E402


def issue(number: int, *labels: str) -> dict:
    return {"number": number, "title": f"이슈 {number}", "labels": [{"name": n} for n in labels]}


def test_layers_match_the_repository_labels():
    """저장소의 레이어 라벨 열두 종. 라벨이 늘면 여기가 먼저 깨진다.

    **순서가 계약이다** (#777 → #794). :func:`layer_of`가 이 목록 순서로 첫
    라벨을 쓰므로, 순서가 바뀌면 두 라벨이 함께 붙은 이슈의 귀속이 **조용히**
    바뀐다.

    구성은 두 묶음이다 — **계층 스택**(정보 구조 그대로: 기반·계산·선대·선박·
    항차·산출물)과 **계층을 가로지르는 축**(계정·어시스턴트·화면 규격·플랫폼·
    검증). 폐지한 ``layer:cross``는 **맨 뒤에 남긴다**: 지우면 닫힌 이슈 59건의
    이력이 사라지고, 목록에서 빼면 그 라벨만 달린 open 이슈가 ``(미부착)``으로
    떨어진다(`#93`이 08-22에 겪은 상태). ``#777``이 ``layer:backlog``에 그렇게
    했던 것을 되풀이하지 않는다.
    """
    assert [label for label, _ in LAYERS] == [
        "layer:base",
        "layer:calc",
        "layer:fleet",
        "layer:vessel",
        "layer:voyage",
        "layer:report",
        "layer:account",
        "layer:assistant",
        "layer:ui",
        "layer:platform",
        "layer:assurance",
        "layer:cross",
    ]


def test_unlabeled_issues_do_not_disappear():
    """라벨을 빠뜨린 이슈가 표에서 사라지면 「없는 것」이 된다.

    `#93`이 2026-08-22에 겪은 상태다 — 미부착 4건이 어느 레이어에도 세어지지
    않아 합계가 어긋났다.
    """
    grouped = summarize([issue(1), issue(2, "bug")])

    assert [row["number"] for row in grouped[UNLABELED]] == [1, 2]
    assert UNLABELED in render([issue(1)])


def test_no_unlabeled_row_when_every_issue_has_a_layer():
    """0건이면 행을 내지 않는다 — 0이 아닐 때만 신호가 된다."""
    assert UNLABELED not in render([issue(1, "layer:cross")])


def test_an_issue_with_two_layers_is_counted_once():
    """두 번 세면 합계가 열린 이슈 수와 달라지고 그 차이를 설명할 수 없다."""
    grouped = summarize([issue(1, "layer:voyage", "layer:cross")])

    counted = sum(len(rows) for rows in grouped.values())
    assert counted == 1
    # 앞선 레이어를 쓴다 — `LAYERS` 순서가 곧 우선순위다.
    assert layer_of(issue(1, "layer:voyage", "layer:cross")) == "layer:voyage"


def test_total_equals_the_number_of_issues():
    issues = [issue(1, "layer:base"), issue(2, "layer:cross"), issue(3)]

    table = render(issues)
    assert "| **합계** | **3** | |" in table


def test_every_layer_gets_a_row_even_when_empty():
    """비어 있는 레이어도 행을 낸다 — 사라지면 「그 레이어가 없다」로 읽힌다."""
    table = render([issue(1, "layer:cross")])

    for _, name in LAYERS:
        assert name in table
