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

#: 항차·시나리오 거리 ``NUMERIC(12,2)`` · 속력 ``NUMERIC(6,2)`` · 항차 연료 ``NUMERIC(12,4)`` ·
#: 정박 연료·거리 ``NUMERIC(12,2)`` — ORM 모델과 같다(검사가 대조).
DISTANCE = storable(12, 2)
SPEED = storable_from(Decimal("1.0"), 6, 2)
VOYAGE_FUEL = storable(12, 4)
NOT_UNDERWAY_FUEL = storable(12, 2)
NOT_UNDERWAY_DISTANCE = {"ge": Decimal(0), "le": largest(12, 2)}
