"""IMO 선박 번호의 검사숫자 (`#2134` · 결정 D-15).

IMO 번호 일곱 자리 중 **마지막 자리는 검사숫자**다 — 앞 여섯 자리에 왼쪽부터 7·6·5·4·3·2를
곱해 더한 값의 1의 자리가 마지막 자리와 같아야 한다. 예: ``9074729`` →
``9×7 + 0×6 + 7×5 + 4×4 + 7×3 + 2×2 = 139`` → 9.

## 왜 검사하는가

IMO 번호는 공적 기록 대조(`#1197`)와 선박 식별의 열쇠다. 한 자리 오타는
형식(숫자 7자리)을 그대로 통과하고, 대조에서 **다른 배로 짝지어질 수 있다.** 검사숫자는 앞
여섯 자리 안의 이웃한 두 자리 뒤바뀜과 한 자리 오타 대부분을 잡는다 — 다 잡지는 못한다.
가중치가 짝수(6·4·2)인 자리에서 5만큼 틀리면 합의 1의 자리가 그대로다.

## 어디서 쓰는가

- 서버 ``api/schemas/vessel.py``의 등록 요청(``VesselCreateRequest.imo_number``)
- 화면 ``frontend/src/features/vessel-registration/formRules.ts``의 ``imoCheckDigitOk`` —
  **같은 식**이다. 서버 ``tests/test_imo_number.py``와 화면 ``formRules.test.ts``가 **같은
  표본**(실선 번호와 그 오타)을 각각 검사해 두 쪽이 갈리면 어느 한쪽이 실패한다

수정(``PATCH``)은 ``imo_number``를 받지 않으므로(`API_SPEC §2.4`) 이미 저장된 번호에는 닿지
않는다. DB CHECK(``chk_imo_format``)는 형식만 본다 — 검사숫자는 입구에서 막는다.

CSV 가져오기(`API_SPEC §8.2`)는 선박을 URL의 ``vessel_id``로 고르고 IMO 번호를 받지 않는다 —
이 검사를 연결할 칸이 없다.
"""

from __future__ import annotations

#: 검사숫자가 맞지 않을 때의 문구 — `API_SPEC §11` VAL-003. 화면도 같은 문장을 쓴다.
IMO_CHECK_DIGIT_MESSAGE = "IMO 번호 검사숫자가 맞지 않습니다."

#: 앞 여섯 자리에 곱하는 수.
_WEIGHTS = (7, 6, 5, 4, 3, 2)


def imo_check_digit(first_six: str) -> int:
    """앞 여섯 자리로 검사숫자를 계산한다."""
    if len(first_six) != len(_WEIGHTS) or not first_six.isascii() or not first_six.isdigit():
        raise ValueError(f"IMO 번호 앞 여섯 자리가 아닙니다: {first_six!r}")
    return sum(int(d) * w for d, w in zip(first_six, _WEIGHTS, strict=True)) % 10


def imo_check_digit_ok(number: str) -> bool:
    """숫자 7자리이고 마지막 자리가 검사숫자와 같은가. 형식이 다르면 ``False``."""
    if len(number) != 7 or not number.isascii() or not number.isdigit():
        return False
    return imo_check_digit(number[:6]) == int(number[6])
