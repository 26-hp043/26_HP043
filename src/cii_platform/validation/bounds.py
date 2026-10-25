"""요청 스키마의 **저장 가능 범위** — DB ``NUMERIC(precision, scale)``에서 계산한다.

`#860` · `#1086`.

## 왜 필요한가

요청 스키마가 ``gt=0``만 보면 DB는 고정 정밀도라 **API를 통과한 값이 저장 단계에서 죽는다** —
``0.001``은 ``0.00``으로 반올림돼 ``chk_*_positive`` 위반, ``1e10``은 정밀도 초과. 둘 다
사용자에게 **원인 설명 없는 500**이다. `#860`이 선박 제원에서 이것을 고쳤고, `#1086`이
항차·시나리오·정박 요청과 CSV 파서까지 같은 규칙으로 넓혔다.

## 도메인 하한이 아니다

경계는 **저장 형식에서 나온다** — 가장 작은 저장 가능한 양수(``10^-scale``)와 가장 큰 값
(``10^(precision-scale) − 10^-scale``). 「거리는 최소 1 nm」 같은 도메인 판단은 여기서
정하지 않는다. 소수 아래 자릿수는 **막지 않는다** — 받아서 DB가 반올림한다.

값은 ORM 모델의 ``Numeric(precision, scale)``과 같아야 하며 ``tests/test_vessel_spec_bounds.py``
·``tests/test_request_bounds.py``가 둘을 대조한다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import AfterValidator


def smallest_positive(scale: int) -> Decimal:
    """``NUMERIC(_, scale)``이 담을 수 있는 가장 작은 양수."""
    return Decimal(1).scaleb(-scale)


def largest(precision: int, scale: int) -> Decimal:
    """``NUMERIC(precision, scale)``이 담을 수 있는 가장 큰 값."""
    return Decimal(10) ** (precision - scale) - smallest_positive(scale)


def storable(precision: int, scale: int) -> dict[str, Decimal]:
    """양수 컬럼용 ``Field(**storable(p, s))`` — ``ge``·``le``."""
    return {"ge": smallest_positive(scale), "le": largest(precision, scale)}


def storable_from(floor: Decimal, precision: int, scale: int) -> dict[str, Decimal]:
    """하한이 도메인에서 오는 컬럼용(속력 ``>= 1.0`` 등) — 상한만 저장 형식에서 온다."""
    return {"ge": floor, "le": largest(precision, scale)}


def to_scale(value: Decimal | None, scale: int) -> Decimal | None:
    """값을 컬럼 소수 자릿수(``scale``)의 **고정 소수 표기**로 맞춘다 (`#2502`).

    드라이버가 파라미터를 SQL 리터럴로 인라인하므로 ``1E+1``·``1E-7`` 같은 지수 표기와
    컬럼 scale을 넘는 긴 소수는 ``CAST(... AS NUMERIC(p,s))`` 문법 오류·``Data overflow``로
    500이 됐다. 소수 아래 자릿수를 거절하지 않고 반올림한다는 종전 정책(위 docstring)을 따라
    ``ROUND_HALF_UP``(0에서 먼 쪽 — DB 반올림과 같다)으로 scale에 맞춘다. 범위(``ge``·``le``)는
    이 검증기보다 앞서 이미 통과했고 경계가 scale 격자 위에 있어 반올림이 범위를 벗어나지 않는다.
    값의 크기는 그대로이고 표기만 바뀐다 — ``"1.5E+1"`` → ``Decimal("15.00")``.

    범위 검사가 먼저이므로 하한 바로 아래 값(``ge`` 0.01인 칸의 ``0.005``)은 반올림하면 0.01이
    되더라도 이미 422로 끝난다 — 「거절하지 않고 반올림」은 범위 **안**의 값에 대한 말이다.
    """
    if value is None:
        return None
    with localcontext() as ctx:
        # 기본 28자리면 quantize가 InvalidOperation — 정수부+scale보다 충분히 크게 둔다.
        ctx.prec = 200
        quantized = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    # 「-0.000000」 같은 음의 0을 남기지 않는다 — 부호만 다른 같은 값이다.
    return quantized if quantized else abs(quantized)


def stored(scale: int) -> AfterValidator:
    """저장 컬럼 ``NUMERIC(_, scale)`` 입력용 — ``Annotated[Decimal, Field(**범위), stored(2)]``.

    ``Field`` 제약 **뒤에** 둔다(범위를 먼저 본 뒤 표기를 맞춘다). ``None``은 그대로 통과한다.
    """
    return AfterValidator(lambda v: to_scale(v, scale))


#: 규제연도 입력의 **하한** — 조회·계산·저장이 모두 같다 (`#2190` 결정 1). BlueLog의 입력
#: 정책이며 「IMO가 2019를 법적 최저 연도로 정했다」는 뜻이 아니다.
MIN_REGULATION_YEAR = 2019
#: 규제연도 **조회·계산**의 상한 — 실시간 CII·이력·연간 시뮬레이션 등 (`#2190` 결정 2).
MAX_REGULATION_YEAR = 2100
#: 규제연도 **저장**의 상한 — ``voyage.regulation_year`` · ``not_underway_period.regulation_year``의
#: DB CHECK(``BETWEEN 2019 AND 2050`` — 마이그레이션 005·025 · `DB_SCHEMA §2.2`)와 같다 (`#2190`).
MAX_STORED_REGULATION_YEAR = 2050

#: 조회·계산이 받는 규제연도 ``2019~2100`` — ``Field(**REGULATION_YEAR)`` · ``Query(**…)``.
REGULATION_YEAR = {"ge": MIN_REGULATION_YEAR, "le": MAX_REGULATION_YEAR}
#: 항차·정박 구간이 **저장하는** 규제연도 ``2019~2050``. 종전 스키마의 ``2000~2100``은
#: 형식만 보는 값이라 2010·2080이 DB에서 500으로 죽었다 (`#1086` ①).
STORED_REGULATION_YEAR = {"ge": MIN_REGULATION_YEAR, "le": MAX_STORED_REGULATION_YEAR}

#: 공적 기항 기록의 입항연도(``call_year``) ``2000~2100``. **규제연도가 아니다** — 기록 한
#: 건을 찾는 키라 규제연도 하한을 적용하지 않는다 (`#2190` 결정 3 · `API_SPEC §3.12`).
CALL_YEAR = {"ge": 2000, "le": 2100}

#: 운항 속력의 물리 상한(kn) — ``PRD §9.1`` VAL-009 (`#1269` · 결정 G-10).
#:
#: **이것은 저장 형식이 아니라 도메인 상한이다** — ``NUMERIC(6,2)``의 상한 9,999.99는
#: 「운항할 수 없는 값」을 하나도 막지 못했다(``120`` kn은 연료 모델 속력 배율 1,000).
#: 60은 현역 페리 세계 최고속 HSC Francisco 58.1 kn(Guinness 「Fastest ferry」)을 막지
#: 않는 가장 좁은 값이다 — 이 제품은 고속선(``RO_RO_PASSENGER_HSC``)을 등록받는다.
#: 자릿수 실수(12.5 → 125)는 막고, 옆 키 오타(15 → 35)는 상한이 아니라 경고의 몫이다.
#: DB 트리거(마이그레이션 ``062``)와 화면 규칙이 같은 값을 쓴다.
MAX_SPEED_KN = Decimal("60")

#: 항차·시나리오 거리 ``NUMERIC(12,2)`` · 항차 연료 ``NUMERIC(12,4)`` · 정박 연료·거리
#: ``NUMERIC(12,2)`` — ORM 모델과 같다(검사가 대조).
DISTANCE = storable(12, 2)
#: 운항 속력 — 하한 1.0(VAL-009) · 상한 60(VAL-009). 둘 다 도메인 값이다.
SPEED = {"ge": Decimal("1.0"), "le": MAX_SPEED_KN}
#: 선박 기준 속력 — 하한은 저장 형식(``0.01`` · VAL-002), 상한은 운항 속력과 같다(VAL-009).
REFERENCE_SPEED = {"ge": smallest_positive(2), "le": MAX_SPEED_KN}
VOYAGE_FUEL = storable(12, 4)
#: 일일 연료(t/일) ``NUMERIC(8,2)`` — 선박 기준 일일 연료(``vessel.reference_daily_foc_ton``)와
#: 시나리오 비교의 ``base_daily_foc_ton``은 **같은 양**이라 같은 범위를 쓴다 (`#2091`).
DAILY_FOC = storable(8, 2)
#: 항만명 최대 길이 — ``voyage.departure_port_name``·``arrival_port_name`` ``VARCHAR(200)``.
#: 항차 생성·수정과 시나리오 채택 요청이 같은 상수를 쓴다 (`#2091`).
PORT_NAME_MAX_LENGTH = 200
NOT_UNDERWAY_FUEL = storable(12, 2)
NOT_UNDERWAY_DISTANCE = {"ge": Decimal(0), "le": largest(12, 2)}
#: 선체·추진 상태 보정(%) — 저장은 ``vessel.hull_condition_percent NUMERIC(5,2)``(`#2561` · 071).
#: **도메인 범위다** — 파울링은 연료를 늘리고(+) 선체 청소·프로펠러 연마·절감장치는
#: 줄인다(−). 상한 100은 GloFouling 보고서(2022)의 석회질 오손 최대치(+60~90%)를 막지 않는
#: 가장 좁은 값, 하한 −30은 절감 쪽 자릿수 실수(−3 → −30 너머)를 막는다. 선박 제원과
#: 시나리오 비교의 덮어쓰기 값은 **같은 양**이라 같은 범위를 쓴다. DB 트리거(071)와 화면
#: 규칙이 같은 값을 쓴다.
HULL_CONDITION_PERCENT = {"ge": Decimal("-30"), "le": Decimal("100")}
