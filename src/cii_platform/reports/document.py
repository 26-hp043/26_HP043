"""포맷 중립 리포트 문서 모델 (PRD §25, #361).

**수치는 여기서 확정된다.** CSV·HTML·PDF 렌더러는 이 구조를 읽기만 하고 값을 만들지
않는다 — ``PRD §25.4``가 *"PDF용 수치를 별도로 계산하면 포맷마다 값이 갈린다"* 를
경고하는 지점이다.

문서는 **제목 + 메타 + 섹션 목록**이다. 섹션은 둘 중 하나다.

* :class:`KeyValueSection` — 항목·값 쌍 (항차 요약, 목표 현황)
* :class:`TableSection` — 머리글 + 행 (연료 내역, 연도별 추이, 시나리오 비교)

두 형태로 충분한 이유는 리포트가 **문서이지 화면이 아니기** 때문이다. 차트·배지는
PDF에서 잉크만 쓰고 CSV에서는 표현되지 않아, 두 포맷이 같은 내용을 담지 못하게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: ``PRD §6.3`` 리포트 문서 면책 문구. **문서 본문에 필수로 노출**된다 —
#: 화면 게시만으로는 부족하다(``PRD §25.1``). 문서가 화면 밖으로 반출되기 때문이다.
#:
#: 문자열을 여기 한 곳에 두는 이유는, 렌더러마다 따로 적으면 한쪽만 고쳐질 때
#: PDF와 CSV의 면책이 달라지기 때문이다.
DISCLAIMER = "본 리포트는 참고용 예측값입니다. 규제 제출용 공식 문서가 아닙니다."

#: 등급이 붙지 않는 값에 붙이는 각주 (``PRD §25.2`` · ``COR-1``).
VOYAGE_CII_NOTE = "항차 단위 CII는 공식 등급 지표가 아닙니다. 등급은 연간 누적(YTD)에만 해당합니다."


@dataclass(frozen=True)
class KeyValueSection:
    """항목·값 쌍 섹션.

    값을 ``str``로 고정한다. ``Decimal``이나 ``float``을 넘기면 렌더러마다
    포맷팅이 갈리고, 그 순간 「같은 데이터에서 렌더링한다」가 깨진다. 서비스가
    ``API_SPEC §1.7`` 규칙으로 문자열을 만들어 넣는다.
    """

    title: str
    rows: list[tuple[str, str]]
    #: 섹션 아래에 붙는 각주. `COR-1` 같은 표기 의무를 싣는다.
    note: str | None = None


@dataclass(frozen=True)
class TableSection:
    """머리글 + 행 섹션.

    ``rows``의 각 행은 ``headers``와 길이가 같아야 한다. 어긋나면 CSV 열이 밀려
    다음 열의 값으로 읽히므로, :meth:`validate`가 문서를 만든 쪽에서 잡는다.
    """

    title: str
    headers: list[str]
    rows: list[list[str]]
    note: str | None = None

    def validate(self) -> None:
        for index, row in enumerate(self.rows):
            if len(row) != len(self.headers):
                raise ValueError(
                    f"{self.title}: {index}행의 열 수가 머리글과 다릅니다 "
                    f"({len(row)} != {len(self.headers)})"
                )


Section = KeyValueSection | TableSection


@dataclass(frozen=True)
class ReportDocument:
    """리포트 한 건.

    :param slug: 파일명에 쓰는 짧은 식별자. 한글 파일명은 브라우저·OS에 따라
        깨지므로 ASCII로 둔다(``Content-Disposition``의 ``filename*``로 한글
        이름을 함께 보낸다).
    """

    title: str
    slug: str
    #: 표지에 싣는 항목 (선박명·기준 시각·생성 시각 등).
    meta: list[tuple[str, str]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    #: 계산 경고(``API_SPEC §1.6``). 문서에 함께 실어야 독자가 값의 한계를 안다.
    warnings: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """표 섹션의 열 수를 확인한다. 문서를 만든 쪽에서 잡아야 할 오류다."""
        for section in self.sections:
            if isinstance(section, TableSection):
                section.validate()
