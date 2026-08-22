"""문서에 싣는 표시 문구 (#584 · #631).

## 왜 서버가 문구를 갖는가

**보고서 PDF는 서버가 만든다.** 문서에 ``BULK_CARRIER``·``CRITICAL``·``REFERENCE_ONLY``가
그대로 나가면 읽는 사람은 그것이 무엇인지 모른다 — 심사·대외 제출에 나가는 산출물이라
더 그렇다. 화면에는 이미 한국어가 있는데 문서만 코드를 냈다.

## 두 종류를 구분한다 (``AGENTS §4.6``)

======================  ==========================================  ==========================
구분                    이 파일에서                                  옮겨 적는 곳
======================  ==========================================  ==========================
**정본 문구**           :data:`RISK_LABELS`                          ``DESIGN_SYSTEM §2.5 (b)`` 🔒
                        :data:`WARNING_LABELS`                       ``API_SPEC §1.6``
**표시 문구**           :data:`SHIP_TYPE_LABELS`                     ``shipTypes.ts``
                        :data:`PROJECTION_REASON_LABELS`             ``realtimeRules.ts``
                        :data:`VOYAGE_STATUS_LABELS`                 ``voyageRules.ts``
                        :data:`INCLUSION_POLICY_LABELS`              ``voyageRules.ts``
======================  ==========================================  ==========================

**정본 문구**는 정본이 원문을 확정한 것이라 바꾸려면 정본 개정이 먼저다. **표시 문구**는
디자인 담당이 문서 개정 없이 바꿀 수 있으며, 화면 쪽이 원본이다.

**어느 쪽이든 표기를 여기서 새로 정하지 않는다.** 옮겨 적기만 하고, 어긋나면
``tests/test_reports.py``의 동기화 테스트가 실패한다 — 정본 문구는 정본과, 표시 문구는
화면과 대조한다.

## 경고 문구의 사슬

``#630``·``#641``이 세운 순서를 그대로 잇는다. 서버는 화면을 거치지 않고 정본에서 직접
받는다 — 화면을 경유하면 화면이 틀렸을 때 문서도 같이 틀린다.

.. code-block:: text

   TECH_SPEC §12.3 ─▶ API_SPEC §1.6 ─┬─▶ frontend/…/resultRules.ts  WARNING_MESSAGE
       (정본)            (전사)       └─▶ reports/labels.py          WARNING_LABELS

## 코드가 목록에 없으면 코드를 그대로 보여 준다

빈칸으로 두면 「값이 없는 것」으로 읽힌다. 새 코드가 들어왔는데 표기가 아직 없는 상태와,
값이 비어 있는 상태는 다르다. 조용히 감추면 **경고가 사라진다** — 화면의
``warningMessage()``가 ``?? code`` 갈래를 두는 것과 같은 판단이다.
"""

from __future__ import annotations

#: 선종 표시 문구. 화면(``shipTypes.ts``)과 같은 값이며 순서는 ``PRD §3.4.3`` 표를 따른다.
SHIP_TYPE_LABELS: dict[str, str] = {
    "BULK_CARRIER": "벌크선",
    "GAS_CARRIER": "가스운반선",
    "TANKER": "탱커",
    "CONTAINER_SHIP": "컨테이너선",
    "GENERAL_CARGO_SHIP": "일반화물선",
    "REFRIGERATED_CARGO_CARRIER": "냉동화물선",
    "COMBINATION_CARRIER": "겸용선",
    "LNG_CARRIER": "LNG운반선",
    "RO_RO_CARGO_VEHICLE": "차량운반선",
    "RO_RO_CARGO": "로로화물선",
    "RO_RO_PASSENGER": "로로여객선",
    "RO_RO_PASSENGER_HSC": "로로여객선(고속선)",
    "CRUISE_PASSENGER": "크루즈여객선",
}

#: 위험도 표시 문구 — ``DESIGN_SYSTEM §2.5 (b)`` 🔒 · ``§14``.
#:
#: **영문 약어를 뒤에 병기한다.** 정본이 「낮음 LOW · 보통 MEDIUM · 높음 HIGH ·
#: 심각 CRITICAL」로 못박았고, ``§14`` 접근성이 「한국어 라벨 + 영문 약어 병기」를
#: 요구한다. 한국어만 남기면 화면(``riskLabel()``)과 문서가 갈리고, 문서에서 본
#: 「심각」과 API 응답의 ``CRITICAL``을 같은 값으로 잇지 못한다.
#:
#: 아이콘은 옮기지 않는다 — ``§2.5``의 ``⚠``는 화면 전용 임시 글리프이며, CSV에
#: 실으면 인코딩에 따라 깨진다.
RISK_LABELS: dict[str, str] = {
    "LOW": "낮음 LOW",
    "MEDIUM": "보통 MEDIUM",
    "HIGH": "높음 HIGH",
    "CRITICAL": "심각 CRITICAL",
}

#: 계산 경고 문구 — ``API_SPEC §1.6``을 그대로 전사했다 (정본은 ``TECH_SPEC §12.3``).
#:
#: 화면의 ``WARNING_MESSAGE``와 **같은 표에서 각자 옮겨 적은 것**이지, 서로를 베낀 것이
#: 아니다. 한쪽이 낡으면 다른 쪽이 아니라 정본과의 대조에서 잡힌다.
WARNING_LABELS: dict[str, str] = {
    "REFERENCE_ONLY": "참고용 예측값입니다. 규제 제출용이 아닙니다.",
    "WEATHER_STALE": "오래된 기상 데이터를 사용 중입니다.",
    "WEATHER_NONE_FALLBACK": "기상 보정 없이 계산했습니다.",
    "CB_ESTIMATED": "선형 계수가 추정값입니다.",
    "EXPERIMENTAL_MODEL": "실험 모델 기반 결과입니다.",
    "NON_CII_VESSEL": "공식 CII 적용 대상이 아닐 수 있습니다.",
    "CII_APPLICABILITY_UNKNOWN": (
        "총톤수(GT)가 없어 공식 CII 적용 대상 여부를 판정할 수 없습니다. "
        "선박 제원에 총톤수를 입력해 주세요."
    ),
    "COMPLETED_NO_FUEL": "실적이 입력되지 않은 완료 항차입니다. 계획값을 임시 사용 중.",
    "COMPLETED_NO_DISTANCE": "실거리가 입력되지 않은 완료 항차입니다. 계획거리를 임시 사용 중.",
    "SLOW_SPEED_FLOOR": (
        "감속 시나리오가 최소 속도(1.0kn)로 운항합니다. 속도 기반 연료 추정의 신뢰도가 낮습니다."
    ),
    "SIMULATION_NO_FUEL_RATE": (
        "선박에 기준 일일 연료소모량이 등록되지 않아 진행 중 항차분이 누적에 "
        "반영되지 않았습니다. 선박 제원을 입력해 주세요."
    ),
    "SIMULATION_NO_FUEL_TYPE": (
        "진행 중 항차의 연료 종류를 알 수 없어 진행분이 누적에 반영되지 않았습니다. "
        "항차에 연료를 입력하거나 선박 기본 연료를 지정해 주세요."
    ),
    "IN_PROGRESS_PAST_ETA": (
        "진행 중 항차가 도착 예정일을 지났습니다. 누적은 예정일까지만 반영했으며, "
        "도착 실적을 입력하면 확정됩니다."
    ),
    "NO_COMPLETED_VOYAGES": (
        "누적 실적이 없어 현재 CII는 계산할 수 없습니다. 잔여 계획 기반 예측만 수행할 수 있습니다."
    ),
    "NO_REMAINING_VOYAGES": (
        "잔여 계획 항차가 없어 확정 실적만으로 연말 예상 등급을 산출했습니다."
    ),
    "MANY_REMAINING_VOYAGES": "잔여 항차가 많아 계산 시간이 길어질 수 있습니다.",
    "SIMULATION_RUNS_CLAMPED": "시뮬레이션 횟수를 허용 범위(1,000~10,000)로 조정했습니다.",
    "TARGET_RATING_D": "목표 등급 D는 위험 구간입니다.",
    "SENSITIVITY_ONE_AT_A_TIME": "각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다.",
    "SENSITIVITY_SPEED_SKIPPED": (
        "선박 제원이 없어 속도 민감도를 산출하지 못했습니다. 표의 속도 항목은 "
        "「효과 없음」이 아니라 「계산되지 않음」입니다."
    ),
}

#: 연말 예상을 내지 못한 사유 — 화면(``realtimeRules.ts`` ``PROJECTION_REASONS``)과 같은 값.
#:
#: **사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.** 문서는 화면과 달리 다시 불러올 수
#: 없으므로 더 그렇다.
PROJECTION_REASON_LABELS: dict[str, str] = {
    "NO_BASIS": (
        "올해 실적이 아직 없어 연말 예상을 산출할 수 없습니다. 항차 실적을 입력하면 계산됩니다."
    ),
    "YEAR_COMPLETE": "해당 연도가 끝나 연말 예상 대신 확정 누적값을 보시면 됩니다.",
}

#: 항차 상태 — 화면(``voyageRules.ts`` ``STATUS_LABELS``)과 같은 값.
VOYAGE_STATUS_LABELS: dict[str, str] = {
    "DRAFT": "작성 중",
    "PLANNED": "계획 확정",
    "IN_PROGRESS": "항해 중",
    "COMPLETED": "항해 완료",
    "CONFIRMED": "실적 확정",
    "CANCELLED": "취소됨",
    "ARCHIVED": "보관됨",
}

#: 연간 집계 반영 정책 — 화면(``voyageRules.ts`` ``POLICY_LABELS``)과 같은 값.
INCLUSION_POLICY_LABELS: dict[str, str] = {
    "EXCLUDE": "연간 반영 안 함",
    "INCLUDE_AS_PLAN": "연간 반영 — 계획",
    "INCLUDE_AS_ACTUAL": "연간 반영 — 실적",
}


#: CII 적용 대상 판정 3상태의 리포트 표기 (`#653`).
#:
#: 화면 배지(`DESIGN_SYSTEM §8`)와 **같은 판정을 다른 매체로 옮긴 것**이다. 리포트는
#: 심사·대외 제출에 나가므로 「미해당」을 빈칸이나 생략으로 두지 않는다 — 값이 없으면
#: 읽는 사람이 「해당」으로 읽는다.
#: 코드는 ``services.applicability``의 3상태다. 이 파일은 다른 라벨 표와 마찬가지로
#: **판정하지 않고 옮겨 적기만 한다** — 판정을 여기서 하면 서비스와 문서가 갈린다.
APPLICABILITY_LABELS: dict[str, str] = {
    "APPLICABLE": "해당 (GT 5,000 이상)",
    "NOT_APPLICABLE": "미해당 (GT 5,000 미만) — 내부 분석용",
    "UNKNOWN": "판정 불가 (총톤수 미입력) — 내부 분석용",
}


def _label(code: str | None, table: dict[str, str]) -> str:
    """코드를 표시 문구로. 없으면 코드를 그대로, 비어 있으면 ``—``를 돌려준다."""
    if not code:
        return "—"
    return table.get(code, code)


def ship_type_label(code: str | None) -> str:
    """선종 코드를 표시 문구로. 없으면 코드를 그대로 돌려준다."""
    return _label(code, SHIP_TYPE_LABELS)


def risk_label(code: str | None) -> str:
    """위험도 코드를 표시 문구로 (``낮음 LOW`` 형태)."""
    return _label(code, RISK_LABELS)


def warning_label(code: str | None) -> str:
    """경고 코드를 사용자 메시지로. 모르는 코드는 감추지 않고 그대로 보인다."""
    return _label(code, WARNING_LABELS)


def applicability_label(code: str | None) -> str:
    """CII 적용 대상 3상태 코드를 리포트 표기로 (`#653`)."""
    return _label(code, APPLICABILITY_LABELS)


def projection_reason_label(code: str | None) -> str:
    """연말 예상을 내지 못한 사유 코드를 문구로."""
    return _label(code, PROJECTION_REASON_LABELS)


def voyage_status_label(code: str | None) -> str:
    """항차 상태 코드를 표시 문구로."""
    return _label(code, VOYAGE_STATUS_LABELS)


def inclusion_policy_label(code: str | None) -> str:
    """연간 집계 반영 정책 코드를 표시 문구로."""
    return _label(code, INCLUSION_POLICY_LABELS)
