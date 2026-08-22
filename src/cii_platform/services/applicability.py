"""CII 적용 대상 판정의 단일 출처 (#653).

``API_SPEC §2.3``이 정한 판정(``gross_tonnage >= 5,000``)은 등록·수정 시점에 서버가
내려 ``vessel.is_cii_applicable_hint``에 굳는다. 이 모듈은 그 판정을 **계산 결과와
문서가 같은 말로 옮기게** 하는 자리다.

## 왜 따로 두는가

판정 규칙이 `services/vessel.py`(등록 시 산정)와 `services/voyage_cii.py`(경고 산정)에
각각 있었고, 임계값 상수(``CII_APPLICABLE_GT_THRESHOLD``)도 두 파일에 따로 있었다.
같은 규칙이 두 곳에 있으면 한쪽만 고쳐진다 — `#653`이 드러낸 것도 결국 **판정은 있는데
그 결과를 옮기는 곳이 한 군데뿐**이라는 문제였다.

## 세 상태다 — 둘이 아니다

``is_cii_applicable_hint``는 boolean이라 「해당/미해당」 둘로 보이지만, **미해당의
원인이 둘**이다.

- ``NOT_APPLICABLE`` — GT를 알고 그것이 5,000 미만이다. 판정이 끝난 상태다
- ``UNKNOWN`` — GT가 ``NULL``이다. **판정할 근거가 없다.** 「적용 대상이 아니다」라고
  단정하면 사용자가 확인된 사실로 읽는다

둘을 합치면 **총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다.**
데모 시드의 실선 2척(``STAR SKIPPER`` · ``DONGJIN ENDURANCE``)이 정확히 후자이며,
`#587`의 제원 조사 회신을 기다리는 중이다.
"""

from __future__ import annotations

from decimal import Decimal

#: ``API_SPEC §2.3`` · ``DB_SCHEMA §2.1`` — ``is_cii_applicable_hint`` 자동 산정 기준.
#: ``PRD §3.1``의 MARPOL Annex VI Reg.28 적용 하한과 같은 값이며, 그 정본은 IMO 원문이다.
CII_APPLICABLE_GT_THRESHOLD = Decimal("5000")

#: ``API_SPEC §1.6`` — GT를 알고 그것이 5,000 미만.
WARNING_NON_CII_VESSEL = "NON_CII_VESSEL"

#: ``API_SPEC §1.6`` — GT가 없어 판정 자체가 불가 (`#653` 신설).
WARNING_CII_APPLICABILITY_UNKNOWN = "CII_APPLICABILITY_UNKNOWN"

#: 판정 3상태. 문자열로 두는 것은 응답에 그대로 실릴 수 있게 하기 위함이 아니라,
#: 서비스 사이에서 뜻이 드러나는 이름으로 오가게 하기 위함이다.
STATE_APPLICABLE = "APPLICABLE"
STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
STATE_UNKNOWN = "UNKNOWN"


def applicability_state(gross_tonnage: Decimal | None) -> str:
    """총톤수로 CII 적용 대상 3상태를 판정한다.

    저장된 ``is_cii_applicable_hint``가 아니라 **GT 원본**을 본다. 힌트는 boolean이라
    ``UNKNOWN``을 표현할 수 없고, 등록 시점에 굳은 값이라 제원이 그 뒤에 바뀌었으면
    현재 GT와 어긋날 수 있다. 판정 근거를 매번 원본에서 다시 읽는다.
    """
    if gross_tonnage is None:
        return STATE_UNKNOWN
    if Decimal(gross_tonnage) < CII_APPLICABLE_GT_THRESHOLD:
        return STATE_NOT_APPLICABLE
    return STATE_APPLICABLE


def applicability_warnings(vessel) -> list[str]:
    """선박 하나에 붙는 CII 적용 대상 경고 (``API_SPEC §1.6``).

    적용 대상이면 빈 목록이다 — **정상 상태에 경고를 붙이지 않는다.**

    호출부가 이 결과를 자기 경고 목록에 이어 붙인다. 계산 결과(기능①·②)·YTD·실시간
    CII·리포트 2종이 모두 같은 함수를 거치므로, 한 화면에만 경고가 붙고 다른 화면은
    조용한 상태가 생기지 않는다.
    """
    state = applicability_state(vessel.gross_tonnage)
    if state == STATE_NOT_APPLICABLE:
        return [WARNING_NON_CII_VESSEL]
    if state == STATE_UNKNOWN:
        return [WARNING_CII_APPLICABILITY_UNKNOWN]
    return []
