"""IMO 번호 검사숫자 (`#2134` · 결정 D-15).

표본은 화면 ``frontend/src/features/vessel-registration/formRules.test.ts``와 **같다** — 두 쪽
식이 갈리면 어느 한쪽이 실패한다. 맞는 번호는 실선 번호(``9074729`` · 시드의 ``9448839`` ·
``9633862``)와 시드 합성 번호(``0000012``)이고, 틀린 번호는 그 오타다.
"""

from __future__ import annotations

import pytest

from cii_platform.imo_number import imo_check_digit, imo_check_digit_ok

VALID = ["9074729", "9448839", "9633862", "0000012", "1234567"]

#: 마지막 자리 오타 · 이웃한 두 자리 뒤바뀜 · 검사숫자와 그 앞자리 뒤바뀜.
INVALID = ["9074728", "9704729", "9074792", "1234568", "9448893"]


def test_검사숫자는_앞_여섯_자리에_7부터_2까지_곱한_합의_1의_자리다() -> None:
    # 9×7 + 0×6 + 7×5 + 4×4 + 7×3 + 2×2 = 139 → 9
    assert imo_check_digit("907472") == 9


@pytest.mark.parametrize("number", VALID)
def test_검사숫자가_맞는_번호는_통과한다(number: str) -> None:
    assert imo_check_digit_ok(number)


@pytest.mark.parametrize("number", INVALID)
def test_오타는_검사숫자에서_걸린다(number: str) -> None:
    assert not imo_check_digit_ok(number)


@pytest.mark.parametrize("number", ["", "123456", "12345678", "12345AB", "１２３４５６７"])
def test_숫자_7자리가_아니면_거짓이다(number: str) -> None:
    """전각 숫자는 ``str.isdigit()``이 참이다 — ASCII로 한정하지 않으면 통과한다."""
    assert not imo_check_digit_ok(number)


def test_앞_여섯_자리가_아니면_계산하지_않는다() -> None:
    with pytest.raises(ValueError):
        imo_check_digit("12345")
