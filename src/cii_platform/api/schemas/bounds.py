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
·``tests/test_request_bounds_db.py``가 둘을 대조한다.
"""

from __future__ import annotations

from decimal import Decimal


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


#: ``voyage.regulation_year`` · ``not_underway_period.regulation_year``의 DB CHECK
#: (``BETWEEN 2019 AND 2050`` — 마이그레이션 005·025 · `DB_SCHEMA §2.2`). 종전 스키마의
#: ``2000~2100``은 형식만 보는 값이라 2010·2080이 DB에서 500으로 죽었다 (`#1086` ①).
REGULATION_YEAR = {"ge": 2019, "le": 2050}

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
NOT_UNDERWAY_FUEL = storable(12, 2)
NOT_UNDERWAY_DISTANCE = {"ge": Decimal(0), "le": largest(12, 2)}
