"""포맷 중립 리포트 문서 모델 (PRD §25, #361).

**수치는 여기서 확정된다.** CSV·HTML·PDF 렌더러는 이 구조를 읽기만 하고 값을 만들지
않는다 — ``PRD §25.4``가 *"PDF용 수치를 별도로 계산하면 포맷마다 값이 갈린다"* 를
경고하는 지점이다.

문서는 **제목 + 메타 + 섹션 목록**이다. 섹션은 셋 중 하나다.

* :class:`KeyValueSection` — 항목·값 쌍 (항차 요약, 목표 현황)
* :class:`TableSection` — 머리글 + 행 (연료 내역, 시나리오 비교)
* :class:`ChartSection` — **표를 품은** 차트 (등급 경계 밴드, 연도별 추이)

## 차트는 표를 진다 (`#2002`)

종전에는 두 형태로 충분하다고 적고 차트를 거절했다 — 차트는 PDF에서 잉크만 쓰고 CSV에서는
표현되지 않아, 두 포맷이 같은 내용을 담지 못하게 된다는 이유였다. **그 이유는 지금도
유효하다.** 달라진 것은 규격에 답이 있다는 점이다 — ``PRD §16.4`` 「차트·확률분포는 **표
요약 제공**」.

:class:`ChartSection`은 :class:`TableSection`을 **필드로** 갖는다. 표 없이는 만들 수 없고,
CSV는 그 표를 쓰고 PDF는 차트와 표를 함께 쓴다. 두 포맷의 내용이 갈리지 않는다는 조건을
**타입이 지킨다.** 차트가 그리는 값도 전부 그 표(와 :attr:`ChartSection.markers`)에서
읽는다 — 렌더러가 값을 만들지 않는다는 위 원칙이 차트에도 그대로다.

## 섹션 분기는 소진형이다

렌더러는 섹션 종류마다 ``isinstance``로 갈라 그린다. **``else``에서 조용히 넘어가면 새 종류는
CSV에서 제목만 남고 내용이 사라진다** — 예외도 나지 않는다(`#2002`가 찾은 종전 모양).
그래서 분기의 끝은 ``assert_never``다. 종류를 더하면 타입 검사와 테스트가 먼저 실패한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, assert_never

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

#: 시나리오 사후 비교 표의 「없음」 표지 셋 (`#2092`). ``—``(기록된 값 없음)와 **다른 말**이다.
#:
#: ⚠️ 정본 문구 (`PRD §6.3` 「항차 리포트 — 사후 비교 표지」 · `rlatnals4114` 2026-10-08
#: 확정 · `#2216`) — 바꾸려면 `PRD` 개정이 먼저다(`AGENTS §4.6`).
#:
#: 여기(문서 모델)에 두는 것은 렌더러도 읽어야 하기 때문이다 — HTML의 열 정렬 판정이 이
#: 표지를 값으로 세면 수치 열이 통째로 왼쪽으로 뒤집힌다(`#2004`의 ``—``와 같은 이유).
#: 서비스(``services/report.py``)는 이 이름을 그대로 가져다 쓴다.

#: 그 종류의 시나리오가 **저장된 비교에 없다.** 값이 0이거나 비어 있는 것과 다르다.
SCENARIO_NOT_STORED = "이력 없음"

#: 실적 연료·CII를 **낼 수 없다** — 재료(실적 거리 · 모든 유종의 실적 연료 · 비교가 쓴
#: 용량)가 모자라다.
ACTUAL_CII_NOT_COMPUTABLE = "계산 불가"

#: 실적 행의 등급 칸. 실적에는 저장된 등급이 없고 리포트가 등급을 새로 판정하지 않는다.
ACTUAL_RATING_NOT_RATED = "산출 안 함"

#: 수치 열에 들어올 수 있는 표지의 닫힌 집합. 렌더러의 열 판정이 **세지 않는** 값이다.
ABSENT_MARKERS: frozenset[str] = frozenset(
    {SCENARIO_NOT_STORED, ACTUAL_CII_NOT_COMPUTABLE, ACTUAL_RATING_NOT_RATED}
)


class ReportTime(str):
    """사람이 읽는 시각과 CSV에 싣는 시각을 함께 쥔 값 (`#2151` · `DESIGN_SYSTEM §4.4`).

    ``str`` 그대로는 **미리보기 · PDF가 읽는 형식**(`2026. 10. 8. 14:30` — 화면과 같은 `§4.4`
    형식)이다. CSV는 :attr:`csv`(`2026-10-08 14:30:00 KST`)를 쓴다 — 스프레드시트가 정렬·필터로
    읽는 자리라 자릿수가 고정된 형식이 낫다(`rlatnals4114` 2026-10-08 결정).

    ``KeyValueSection.rows``가 ``str``을 요구하므로 하위 클래스로 둔다 — 렌더러 둘(HTML · PDF)은
    아무것도 바꾸지 않아도 사람이 읽는 형식을 싣는다.
    """

    csv: str

    def __new__(cls, display: str, csv: str) -> ReportTime:
        obj = super().__new__(cls, display)
        obj.csv = csv
        return obj

    def __reduce__(self) -> tuple[type[ReportTime], tuple[str, str]]:
        # ``str`` 하위 클래스의 기본 복사·피클은 인자 하나로 다시 만들려 해 실패한다 — 둘을 넘긴다.
        return (ReportTime, (str(self), self.csv))


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
    #: 이 섹션의 **결론**인 행의 항목명 (`#2002`). 비우면 결론이 없는 섹션이다.
    #:
    #: 위치로 짚지 않고 **선언**한다. 「첫 섹션의 첫 행」을 결론으로 읽는 렌더러는 섹션이나
    #: 행 순서가 바뀌는 날 **조용히 다른 값을 결론으로 인쇄한다.** 둘까지 받는 것은 결론이
    #: 등급과 값 **한 쌍**이기 때문이다(``DESIGN_SYSTEM §8.6`` — 「등급 배지와 값은 한 사실」).
    #: CSV는 이 선언을 쓰지 않는다 — 행은 그대로 전부 나간다.
    lead: tuple[str, ...] = ()

    def validate(self) -> None:
        labels = [label for label, _ in self.rows]
        missing = [label for label in self.lead if label not in labels]
        if missing:
            raise ValueError(f"{self.title}: 결론으로 지정한 행이 없습니다 ({missing})")
        # 결론은 항목명으로 가리키므로 **한 행**이어야 한다. 같은 이름이 둘이면 PDF는 하나만
        # 결론으로 세우고 CSV는 둘 다 내 두 포맷이 갈린다.
        ambiguous = [label for label in self.lead if labels.count(label) > 1]
        if ambiguous:
            raise ValueError(
                f"{self.title}: 결론으로 지정한 항목명이 여러 행에 있습니다 ({ambiguous})"
            )


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


#: 차트의 종류 (`#2002`). 종류마다 품은 표가 가져야 할 열이 정해져 있다.
#:
#: * ``rating_band`` — 등급 경계 밴드. 표 한 행이 한 등급의 구간이다(:data:`BAND_HEADERS`)
#: * ``trend`` — 연도별 추이. 표에 :data:`TREND_COLUMNS`가 있어야 한다
ChartKind = Literal["rating_band", "trend"]

#: 등급 경계 표의 머리글 — **이 순서 그대로**다. 렌더러가 열을 이름으로 찾지 않고 자리로
#: 읽으므로, 순서가 어긋나면 밴드가 다른 열의 값으로 그려진다. :meth:`ChartSection.validate`가
#: 문서를 만든 쪽에서 잡는다.
#:
#: 구간은 **(하한, 상한]** 이다 — 경계값과 정확히 같으면 더 우수한 등급이다(``PRD §3.3.6``).
BAND_HEADERS: tuple[str, ...] = (
    "등급",
    "기준 대비 하한 (%)",
    "기준 대비 상한 (%)",
    "CII 하한",
    "CII 상한",
)

#: 밴드 표의 행 순서. 등급 문자는 **표가 싣는다** — 렌더러가 순서로 A~E를 붙이지 않는다.
BAND_GRADES: tuple[str, ...] = ("A", "B", "C", "D", "E")

#: 추이 차트가 읽는 열. 표에는 다른 열이 더 있어도 된다(연도별 추이는 8열이다).
TREND_COLUMNS: tuple[str, ...] = ("연도", "실적 CII", "기준 CII", "등급")


@dataclass(frozen=True)
class ChartSection:
    """표를 품은 차트 섹션 (`#2002` · ``PRD §16.4``).

    **표 없이는 만들 수 없다** — :attr:`table`이 필수 필드다. CSV는 이 표를 그대로 쓰고,
    PDF는 차트를 그린 뒤 **표를 함께 싣는다**(차트가 있어도 표를 남긴다 — ``§16.4``).

    :attr:`markers`는 차트 위에 표시하는 값(예: 올해 누적의 기준 대비 위치)이다. 표의 행이
    아닌 값이라 따로 두되, **CSV에도 표 아래 항목·값 행으로 나간다** — 차트에만 있는 값은
    이 모델에 둘 자리가 없다.
    """

    chart: ChartKind
    table: TableSection
    markers: list[tuple[str, str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.table.title

    @property
    def note(self) -> str | None:
        return self.table.note

    def validate(self) -> None:
        self.table.validate()
        if self.chart == "rating_band":
            if tuple(self.table.headers) != BAND_HEADERS:
                raise ValueError(
                    f"{self.title}: 등급 밴드 표의 머리글이 규격과 다릅니다 ({self.table.headers})"
                )
            grades = tuple(row[0] for row in self.table.rows)
            if grades != BAND_GRADES:
                raise ValueError(
                    f"{self.title}: 등급 밴드 표의 행이 A~E 순서가 아닙니다 ({grades})"
                )
        elif self.chart == "trend":
            missing = [name for name in TREND_COLUMNS if name not in self.table.headers]
            if missing:
                raise ValueError(f"{self.title}: 추이 차트가 읽을 열이 없습니다 ({missing})")
        else:
            assert_never(self.chart)


Section = KeyValueSection | TableSection | ChartSection


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
        """섹션마다의 규격(표 열 수 · 결론 행 · 차트가 읽을 열)을 확인한다.

        문서를 만든 쪽에서 잡아야 할 오류다. 분기는 소진형이다 — 섹션 종류가 늘면 여기서
        먼저 실패한다(`#2002`).
        """
        for section in self.sections:
            if isinstance(section, (KeyValueSection, TableSection, ChartSection)):
                section.validate()
            else:
                assert_never(section)
