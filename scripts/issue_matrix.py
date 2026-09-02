#!/usr/bin/env python3
"""이슈 디펜던시 매트릭스 — 지금 상태를 세어 표로 낸다 (#93).

## 왜 스크립트인가

`#93`은 **닫지 않는 추적용 메타 이슈**이고, 본문의 「현재 상태」 표를 손으로
갱신해 왔다. 그 표가 **세 번 낡았다** — 2026-07-16 · 08-15 전면 재작성 · 08-22
정정. 한 주만 지나면 같은 상태가 된다.

네 번째 재작성을 예약하는 대신 **세는 일을 명령 하나로** 만든다. 본문에는 변하지
않는 것(레이어 정의 · 선후 관계 · 병목 교훈)만 남기고, 변하는 숫자는 여기서 낸다.

## 왜 라벨로 세는가

`layer:*` 라벨은 이슈를 만들 때 붙고 GitHub가 보관한다 — **문서에 옮겨 적을 필요가
없는 유일한 출처**다. 옮겨 적는 순간 갱신 주체가 사람이 되고, 그것이 지금까지
낡아 온 이유다.

## 쓰는 법

    $ python3 scripts/issue_matrix.py            # 열린 이슈
    $ python3 scripts/issue_matrix.py --state all

`gh`가 로그인돼 있어야 한다. 집계 자체는 :func:`summarize`가 하며, 그 함수는
네트워크를 모른다 — `tests/test_issue_matrix.py`가 그 함수만 본다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

#: 레이어 라벨과 표시 이름. 순서는 `#93` 본문의 레이어 구조를 따른다.
#:
#: **이 축은 「어느 계층인가」에만 답한다** (#777). 종전 `layer:backlog`가
#: 「현 범위 밖」으로 범위 축을 겸하고 있었고, 그 라벨만 달린 이슈는 계층
#: 정보를 갖지 못했다. 「지금 시작할 수 있는가」는 `blocked` 라벨이 답한다.
LAYERS: tuple[tuple[str, str], ...] = (
    ("layer:base", "L0 기반"),
    ("layer:fleet", "L1 선대"),
    ("layer:vessel", "L2 선박"),
    ("layer:voyage", "L3 항차"),
    ("layer:report", "L4 산출물"),
    #
    # `layer:assistant`는 `layer:cross`보다 **앞**이다 (#777). `layer_of()`가 이
    # 순서로 첫 라벨을 쓰므로, 뒤에 두면 횡단 라벨이 함께 붙은 챗봇 이슈가
    # 어시스턴트가 아니라 횡단으로 세어진다.
    #
    ("layer:assistant", "LA 어시스턴트"),
    ("layer:cross", "LX 횡단"),
)

#: 라벨이 없는 이슈를 담는 자리. **빈칸으로 두지 않는다** — 라벨을 빠뜨린 이슈가
#: 표에서 사라지면 「없는 것」이 되고, 그것이 `#93`이 08-22에 겪은 상태다.
UNLABELED = "(미부착)"


def layer_of(issue: dict) -> str:
    """이슈 하나의 레이어. 라벨이 둘 이상이면 :data:`LAYERS` 순서로 앞엣것을 쓴다.

    **여러 레이어에 걸친 이슈를 두 번 세지 않는다.** 두 번 세면 합계가 열린 이슈
    수와 달라지고, 그 차이를 설명할 수 없다.
    """
    names = {label["name"] for label in issue.get("labels", [])}
    for label, _ in LAYERS:
        if label in names:
            return label
    return UNLABELED


def summarize(issues: list[dict]) -> dict[str, list[dict]]:
    """레이어별로 묶는다. 키는 :data:`LAYERS` 라벨 또는 :data:`UNLABELED`."""
    grouped: dict[str, list[dict]] = {label: [] for label, _ in LAYERS}
    grouped[UNLABELED] = []
    for issue in issues:
        grouped[layer_of(issue)].append(issue)
    return grouped


def render(issues: list[dict]) -> str:
    """마크다운. `#93` 본문에 그대로 붙여 넣을 수 있는 모양이다."""
    grouped = summarize(issues)
    lines = ["| 레이어 | 열린 이슈 | 번호 |", "|---|---:|---|"]

    for label, name in LAYERS:
        rows = grouped[label]
        numbers = " · ".join(f"#{row['number']}" for row in rows) or "—"
        lines.append(f"| {name} `{label}` | {len(rows)} | {numbers} |")

    unlabeled = grouped[UNLABELED]
    if unlabeled:
        numbers = " · ".join(f"#{row['number']}" for row in unlabeled)
        # 0건이면 행을 내지 않는다 — 0을 보여 주는 것보다 사라지는 편이 읽기 쉽고,
        # 0이 아닐 때만 「붙여야 할 것이 있다」는 신호가 된다.
        lines.append(f"| **{UNLABELED}** ⚠️ | {len(unlabeled)} | {numbers} |")

    lines.append(f"| **합계** | **{len(issues)}** | |")
    return "\n".join(lines)


def fetch(state: str) -> list[dict]:
    """`gh`로 이슈를 읽는다. 여기만 네트워크를 안다."""
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            state,
            "--limit",
            "200",
            "--json",
            "number,title,labels",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="이슈 디펜던시 매트릭스 (#93)")
    parser.add_argument("--state", default="open", choices=("open", "closed", "all"))
    args = parser.parse_args()

    issues = fetch(args.state)
    print(render(issues))
    return 0


if __name__ == "__main__":
    sys.exit(main())
