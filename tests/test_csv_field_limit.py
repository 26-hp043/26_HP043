"""CSV 한 칸이 너무 길 때 가져오기 셋이 500이 아니라 파일 오류(422)로 끝난다 (#2505).

``csv`` 모듈은 한 칸이 131,072자를 넘으면 ``_csv.Error``를 올린다. 항차·정박 구간·규제
파라미터 CSV 가져오기의 ``read_rows`` 셋이 이를 잡지 않아 5MB 이하 파일 하나로 500이
났다. 세 자리는 ``voyage_import.open_csv`` 한 곳을 쓰므로 여기서는 서비스 함수를 직접
불러 DB 없이 본다.
"""

from __future__ import annotations

import pytest

from cii_platform.errors import ValidationError
from cii_platform.services import not_underway_import, parameter_import, voyage_import
from cii_platform.services.voyage_import import (
    CSV_TOO_LONG_CELL_MESSAGE,
    CSV_UNREADABLE_MESSAGE,
)

#: ``csv.field_size_limit()`` 기본값 131,072를 넘는 길이.
LONG = "A" * 140_000


def _csv(columns: tuple[str, ...], cell_in: str) -> bytes:
    """첫 칸에 긴 값을 넣은 한 행짜리 CSV."""
    header = ",".join(columns)
    row = ",".join([LONG if col == cell_in else "x" for col in columns])
    return f"{header}\n{row}\n".encode()


_CASES = [
    pytest.param(
        lambda b: voyage_import.read_rows(b),
        _csv(voyage_import.REQUIRED_COLUMNS, "voyage_no"),
        id="항차",
    ),
    pytest.param(
        lambda b: not_underway_import.read_rows(b),
        _csv(not_underway_import.REQUIRED_COLUMNS, "period_type"),
        id="정박",
    ),
    pytest.param(
        lambda b: parameter_import.read_rows(b, "regulation_years"),
        _csv(("year", "z_factor_percent", "effective_from", "source_ref"), "source_ref"),
        id="파라미터",
    ),
]


@pytest.mark.parametrize(("call", "content"), _CASES)
def test_긴_칸은_파일_단위_422로_거절한다(call, content):
    assert len(content) < voyage_import.MAX_FILE_BYTES  # 크기 가드가 아니라 칸 한도다
    with pytest.raises(ValidationError) as raised:
        call(content)
    assert raised.value.message == CSV_TOO_LONG_CELL_MESSAGE
    assert raised.value.details[0]["field"] == "file"


@pytest.mark.parametrize(("call", "_content"), _CASES)
def test_헤더_줄이_너무_길어도_같다(call, _content):
    with pytest.raises(ValidationError) as raised:
        call((LONG + "\n1\n").encode())
    assert raised.value.message == CSV_TOO_LONG_CELL_MESSAGE


def test_그_밖의_CSV_구문_오류도_영문이_새지_않는다(monkeypatch):
    """``field larger``가 아닌 ``csv.Error``는 일반 문구로 — 영문 원문을 내보내지 않는다."""
    import csv

    def boom(self):
        raise csv.Error("new-line character seen in unquoted field")

    monkeypatch.setattr(csv.DictReader, "__next__", boom)
    with pytest.raises(ValidationError) as raised:
        voyage_import.read_rows(_csv(voyage_import.REQUIRED_COLUMNS, "voyage_no"))
    assert raised.value.message == CSV_UNREADABLE_MESSAGE


def test_정상_CSV는_그대로_읽는다():
    """대조군 — 모든 CSV를 거부해도 위 검사는 통과하므로 정상 경로를 함께 본다."""
    columns = voyage_import.REQUIRED_COLUMNS
    content = (",".join(columns) + "\n" + ",".join("v" for _ in columns) + "\n").encode()
    rows, truncated = voyage_import.read_rows(content)
    assert len(rows) == 1
    assert truncated == 0
