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
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 표 열의 종류 (``API_SPEC §8.5`` · #1247).
#:
#: ``string``은 사용자 입력이 섞일 수 있는 열이고 ``numeric``은 **서버가 Decimal·int에서
#: 만든 수치만** 들어가는 열이다. CSV 렌더러가 이 선언을 보고 문자열 열은 수식 주입
#: 방어(``'`` 접두)를, 수치 열은 숫자 직렬화를 택한다. **값의 모양이 아니라 선언으로만**
#: 가른다 — 값을 보고 「숫자 같으니 접두를 빼자」고 판정하면 그 판정기가 새 취약점이 된다.
ColumnKind = Literal["string", "numeric"]

#: 선언하지 않은 열의 종류. 종전 동작(모든 셀에 접두 방어)이 그대로 유지된다.
DEFAULT_COLUMN_KIND: ColumnKind = "string"

_COLUMN_KINDS: frozenset[str] = frozenset({"string", "numeric"})


def column_kinds(headers: Sequence[str], kinds: Sequence[str] | None) -> list[ColumnKind]:
    """열 종류 선언을 확인하고 머리글 수만큼 채워 돌려준다.

    선언이 없으면 전부 ``string``이다. 선언이 머리글 수와 다르면 열이 밀려 **다른 열의
    종류가 적용**되므로 :class:`TableSection` 열 수 검사와 같은 이유로 여기서 잡는다.
    """
    if kinds is None:
        return [DEFAULT_COLUMN_KIND] * len(headers)
    if len(kinds) != len(headers):
        raise ValueError(f"열 종류 선언 수가 머리글과 다릅니다 ({len(kinds)} != {len(headers)})")
    unknown = [kind for kind in kinds if kind not in _COLUMN_KINDS]
    if unknown:
        raise ValueError(f"알 수 없는 열 종류입니다: {unknown} (string · numeric 중 하나)")
    return list(kinds)  # type: ignore[arg-type]


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

    ``kinds``는 열마다의 :data:`ColumnKind` 선언이다 (#1247). **문서를 만드는 쪽이
    선언한다** — 어느 열이 서버 산출 수치인지는 값을 넣은 쪽만 안다. 비우면 전부
    ``string``이라 종전과 같이 모든 셀이 접두 방어를 받는다. 셀 값 자체는 여전히
    ``str``이다(``TECH_SPEC §19.1``) — 선언은 CSV가 그 문자열을 어떻게 내보내는가만 정한다.
    """

    title: str
    headers: list[str]
    rows: list[list[str]]
    note: str | None = None
    kinds: list[ColumnKind] | None = None

    def validate(self) -> None:
        column_kinds(self.headers, self.kinds)
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
