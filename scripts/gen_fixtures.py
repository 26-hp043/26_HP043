"""Layer 1 정본값 생성기 — `TEST_PLAN §1.7` 계약 구현 (#45).

**서비스 코드(`src/cii_platform/**`)를 import하지 않는다.** 이 파일에 서비스
import가 하나라도 생기면 생성기의 존재 이유가 사라진다 — 서비스에 오류가 있을 때
그 오류가 그대로 정답이 되어 **테스트는 통과하는데 값은 틀린 상태**가 된다.
`#179`가 정확히 그 상태였다.

`TEST_PLAN §1.7`의 독립성 조건 3개를 지킨다.

1. 서비스 코드를 import하지 않는다 — 이 모듈의 import 목록이 `decimal` · 표준
   라이브러리뿐임을 `test_gen_fixtures.py`가 검사한다.
2. **상수는 규정 원문에서 독립 전사**하고 값마다 출처를 주석으로 적는다.
   서비스 상수 파일(`db/seed.py`)에서 옮겨 오면 같은 값이 들어오고, 그 값이
   틀렸을 때 틀린 값을 그대로 정답으로 삼는다.
3. 작업 정밀도는 **정본값 자릿수 + 최소 20**, 확정은 마지막에 한 번만.

**CI에 넣지 않는다.** 값 고정이 목적이므로 픽스처를 추가·변경할 때만 수동 실행한다.

```
python scripts/gen_fixtures.py            # 표준 출력으로 확인
python scripts/gen_fixtures.py --write    # tests/fixtures/cii/ 에 기록
```

**독립 구현만으로는 한계가 있다** — 같은 식을 다시 옮겨 적는 것이라 옮겨 적는
실수는 잡아도 **식 자체가 틀렸으면 같이 틀린다.** 그래서 합격 기준이 수기로
검증이 끝난 `TEST_PLAN §1.2`의 정본값 6개다(`EXPECTED_CANONICAL`).
"""

from __future__ import annotations

import argparse
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# 정밀도 — TECH_SPEC §1.2.1
# ────────────────────────────────────────────────────────────────────────────

#: 공표 시점에 확정하는 **유효숫자** 자릿수. §1.2.1의 「N자리」는 유효숫자다.
CANONICAL_SIGNIFICANT_DIGITS = 30

#: 계산 중 유지하는 작업 정밀도. §1.2.1이 **정본값 자릿수 + 최소 20**을 요구한다.
WORKING_PRECISION = CANONICAL_SIGNIFICANT_DIGITS + 20

ROUNDING = ROUND_HALF_UP

# ────────────────────────────────────────────────────────────────────────────
# 규제 상수 — 원문에서 독립 전사한다 (TEST_PLAN §1.7 조건 2)
#
# ⚠️ 서비스 상수 파일(`src/cii_platform/db/seed.py`)에서 복사하지 않는다.
#    값마다 출처를 적어 두는 이유는, 값이 어긋났을 때 어느 원문을 다시 봐야
#    하는지가 파일 안에서 끝나야 하기 때문이다.
# ────────────────────────────────────────────────────────────────────────────

#: BULK_CARRIER (DWT < 279,000) reference line 계수.
#: 출처: MEPC.353(78) Table 1 (MEPC 78/17/Add.1 Annex 15, 인쇄면 4쪽)
BULK_CARRIER_A = Decimal("4745")
BULK_CARRIER_C = Decimal("0.622")

#: HFO의 탄소 계수 CF (tCO₂/tFuel).
#: 출처: MEPC.364(79) §2.2.1 (G1 §4.1이 참조 지정). G1에는 CF 표가 없다.
HFO_CF = Decimal("3.114")

#: 2026년 감축률 Z (%). 출처: MEPC.400(83)
Z_FACTOR_PERCENT_2026 = Decimal("11")

#: BULK_CARRIER d-vector (A/B · B/C · C/D · D/E 경계 계수).
#: 출처: MEPC.354(78) Table 1
BULK_CARRIER_D_VECTOR = {
    "superior_boundary": Decimal("0.86"),
    "lower_boundary": Decimal("0.94"),
    "upper_boundary": Decimal("1.06"),
    "inferior_boundary": Decimal("1.18"),
}

#: 톤 → 그램. 출처: PRD §3.3.2 `M = Σ(FuelConsumed_j × 1,000,000 × CF_j)`
GRAMS_PER_TON = Decimal("1000000")

# ────────────────────────────────────────────────────────────────────────────
# 합격 기준 — TEST_PLAN §1.2 (수기 검증 완료분)
#
# 독립 구현이 식을 잘못 옮겨 적었을 때 걸러 내는 유일한 장치다.
# 이 값을 생성기 출력으로 갱신하면 장치가 사라지므로 **손으로만 고친다.**
# ────────────────────────────────────────────────────────────────────────────

EXPECTED_CANONICAL = {
    "cii_ref": "5.66861385673728321407947925818",
    "required_cii": "5.04506633249618206053073653978",
    "superior_boundary": "4.33875704594671657205643342421",
    "lower_boundary": "4.74236235254641113689889234739",
    "upper_boundary": "5.34777031244595298416258073217",
    "inferior_boundary": "5.95317827234549483142626911694",
}


def publish(value: Decimal, digits: int = CANONICAL_SIGNIFICANT_DIGITS) -> Decimal:
    """공표 자릿수(유효숫자)로 확정한다.

    고정 exponent로 ``quantize``하면 정수부 자릿수가 다른 값에서 어긋나므로
    :meth:`Decimal.adjusted`로 지수를 잡는다 — ``5.66…``(정수부 1)과
    ``10.09…``(정수부 2)의 소수부 자릿수가 각각 29·28로 달라야 한다.
    """
    if not value.is_finite():
        raise ValueError(f"cannot publish non-finite value: {value}")
    with localcontext(prec=WORKING_PRECISION, rounding=ROUNDING):
        if value.is_zero():
            return Decimal(0)
        return value.quantize(Decimal(1).scaleb(value.adjusted() - digits + 1))


def compute_layer1(prec: int) -> dict[str, Decimal]:
    """작업 정밀도 ``prec``으로 Layer 1 체인을 **중간 확정 없이** 계산한다.

    `TECH_SPEC §1.2.1` 「중간 단계 처리」 — `cii_ref` → `required_cii` → 경계값을
    연속 계산하고, 확정은 공표 시점에 한 번만 한다.

    `TECH_SPEC §1.2.2`가 정한 계산 경로에 따라 `ln`/`exp`를 쓴다. **`Decimal`의
    `**`도 분수 지수를 지원한다** — `Decimal(2) ** Decimal("0.5")`는 동작한다.
    다만 **계산 경로에 따라 작업 정밀도의 하위 자리가 달라질 수 있으므로**,
    재현성을 위해 `ln`/`exp` 경로로 단일화한다(서비스 구현과 같은 경로).
    """
    with localcontext(prec=prec, rounding=ROUNDING):
        capacity = Decimal("50000")
        cii_ref = BULK_CARRIER_A * (-BULK_CARRIER_C * capacity.ln()).exp()
        required = cii_ref * (Decimal(1) - Z_FACTOR_PERCENT_2026 / Decimal(100))
        out = {"cii_ref": cii_ref, "required_cii": required}
        for name, d in BULK_CARRIER_D_VECTOR.items():
            out[name] = required * d
        return out


def check_invariance(base: int = WORKING_PRECISION) -> dict[str, Decimal]:
    """`P` · `P+10` · `P+20`에서 출력이 같은지 확인한다 (`TECH_SPEC §1.2.1`).

    **자릿수를 조금 올리는 것으로는 부족하다** — 31자리는 30자리와 반대 방향으로
    틀린다. 판정 기준은 정밀도 값이 아니라 결과의 안정성이다.
    """
    runs = {
        p: {k: publish(v) for k, v in compute_layer1(p).items()}
        for p in (base, base + 10, base + 20)
    }
    reference = runs[base]
    for prec, values in runs.items():
        if values != reference:
            diff = {k: (reference[k], values[k]) for k in reference if reference[k] != values[k]}
            raise AssertionError(
                f"불변성 검사 실패 — prec={base}와 prec={prec}의 출력이 다르다: {diff}"
            )
    return reference


def check_against_expected(canonical: dict[str, Decimal]) -> None:
    """수기 검증이 끝난 정본값 6개를 재현하는지 확인한다 (`TEST_PLAN §1.7`).

    독립 구현은 **옮겨 적는 실수만 잡는다.** 식 자체가 틀리면 같이 틀리므로,
    이 대조가 생성기의 실질 합격 기준이다.
    """
    mismatch = {
        k: (str(canonical[k]), v)
        for k, v in EXPECTED_CANONICAL.items()
        if canonical[k] != Decimal(v)
    }
    if mismatch:
        raise AssertionError(f"정본값 재현 실패: {mismatch}")


def build_fixture_1(canonical: dict[str, Decimal], raw: dict[str, Decimal]) -> dict:
    """`TEST_PLAN §1.2` Fixture 1.

    종료되는 값(`co2_emission_g` 등)은 **수학적 최소 표기**로, 나누어떨어지지
    않는 값은 **정본값 30자리**로 적는다(`TECH_SPEC §1.2.1` 표기 조항 1).

    ⚠️ **`ratio_to_required`의 분모는 `raw["required_cii"]`다.** 확정된 30자리
    값으로 나누면 끝자리가 갈린다 — `§1.2.1` 「중간 단계 처리」가 금지하는
    형태다. 실제로 확정값을 쓰면 `…012580`, 원값을 쓰면 `…012581`이 나온다.
    """
    with localcontext(prec=WORKING_PRECISION, rounding=ROUNDING):
        fuel_ton = Decimal("80")
        distance = Decimal("1000")
        capacity = Decimal("50000")
        co2_g = fuel_ton * GRAMS_PER_TON * HFO_CF
        co2_ton = co2_g / GRAMS_PER_TON
        attained = co2_g / (capacity * distance)
        ratio = attained / raw["required_cii"]

    return {
        "description": "PRD §13.1 Fixture 1 — Bulk carrier 50,000 DWT, 2026, HFO",
        "input": {
            "ship_type": "BULK_CARRIER",
            "deadweight": 50000,
            "gross_tonnage": 30000,
            "regulation_year": 2026,
            "distance_nm": 1000,
            "speed_kn": 12.0,
            "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 80.0, "cf": 3.114}],
            "weather_model": "NONE",
        },
        "expected": {
            "transport_capacity": "50000",
            "reference_capacity": "50000",
            "reference_capacity_rule": "DWT",
            "co2_emission_g": _minimal(co2_g),
            "co2_emission_ton": _minimal(co2_ton),
            "attained_cii": _minimal(attained),
            "cii_ref": str(canonical["cii_ref"]),
            "required_cii": str(canonical["required_cii"]),
            "superior_boundary": str(canonical["superior_boundary"]),
            "lower_boundary": str(canonical["lower_boundary"]),
            "upper_boundary": str(canonical["upper_boundary"]),
            "inferior_boundary": str(canonical["inferior_boundary"]),
            "estimated_rating": "C",
            "ratio_to_required": str(publish(ratio)),
            "risk_level": "MEDIUM",
        },
        "canonical_digits": {
            "significant": CANONICAL_SIGNIFICANT_DIGITS,
            "fields": [
                "cii_ref",
                "required_cii",
                "superior_boundary",
                "lower_boundary",
                "upper_boundary",
                "inferior_boundary",
                "ratio_to_required",
            ],
        },
        "tolerance": {"layer1_integer": "0", "layer1_decimal": "9", "layer1_display": "6"},
        "fixture_note": _FIXTURE_NOTE,
    }


def build_fixture_2(canonical: dict[str, Decimal], raw: dict[str, Decimal]) -> dict:
    """`TEST_PLAN §1.3` Fixture 2 — 등급 경계값.

    **케이스의 판정 입력을 구체적인 숫자로 적지 않는다.** `boundary` + `offset`으로
    기술하고, 소비자가 **확정 전 원경계에 `offset`을 더해** 만든다.

    구체값을 적으면 **그 값이 곧 틀린 입력이 된다** — `boundaries`는 공표 자릿수로
    확정한 값이고 판정은 `§1.2.1`대로 확정 전 원값과 비교하는데, 확정이 **올림**되면
    확정값이 원경계보다 커져 `PRD §3.3.6`의 ``<=``가 깨진다. `upper`·`inferior`가
    실제로 그 경우이며, 각각 C→D · D→E로 뒤집힌다.

    ``raw``를 인자로 받지만 값을 꺼내 쓰지 않는다. 케이스가 기호 표기라 원경계가
    파일에 들어가지 않기 때문이다. **시그니처는 `build_fixture_1`과 맞춰 둔다** —
    `TARGETS`가 두 빌더를 같은 방식으로 호출한다.
    """
    return {
        "description": "PRD §13.2 Fixture 2 — 등급 경계값 테스트 (BULK_CARRIER, 2026)",
        # 원경계를 재계산하려면 조건이 파일 안에 있어야 한다. 없으면 §1.2를 함께
        # 열어야 소비할 수 있다.
        "input": {
            "ship_type": "BULK_CARRIER",
            "deadweight": 50000,
            "regulation_year": 2026,
        },
        "base_required_cii": str(canonical["required_cii"]),
        "boundaries": {
            "superior": str(canonical["superior_boundary"]),
            "lower": str(canonical["lower_boundary"]),
            "upper": str(canonical["upper_boundary"]),
            "inferior": str(canonical["inferior_boundary"]),
        },
        # 케이스에는 확정 대상 값이 없으므로 cases[].attained_cii 를 넣지 않는다.
        "canonical_digits": {
            "significant": CANONICAL_SIGNIFICANT_DIGITS,
            "fields": ["base_required_cii", "boundaries.*"],
        },
        "cases": [
            {"boundary": b, "offset": o, "expected_rating": r, "note": n}
            for b, o, r, n in [
                ("superior", "0", "A", _BOUNDARY_CASE_NOTE),
                ("lower", "0", "B", _BOUNDARY_CASE_NOTE),
                ("upper", "0", "C", _BOUNDARY_CASE_NOTE),
                ("inferior", "0", "D", _BOUNDARY_CASE_NOTE),
                ("inferior", "0.000001", "E", "inferior + 0.000001 = E [ORACLE-M-2]"),
            ]
        ],
    }


_BOUNDARY_CASE_NOTE = "경계값 = 더 우수한 등급"


_FIXTURE_NOTE = (
    "이 파일의 값이 유일한 기준값이며, 서비스 코드와 독립된 참조 구현체로 생성한다 — "
    "작업 정밀도는 정본값 자릿수 + 최소 20자리, 확정은 마지막에 한 번만 정본값 자릿수(30)로 한다 "
    "(TECH_SPEC §1.2.1). 생성기: scripts/gen_fixtures.py. "
    "정수값(M, W, capacity)은 bit-exact 비교, 소수값은 수치 비교이며 표기 자릿수는 비교 결과에 "
    "영향을 주지 않는다 (TEST_PLAN §9.1). "
    "나누어떨어지지 않는 값의 확정 자릿수는 canonical_digits 블록에 적는다."
)


def _minimal(value: Decimal) -> str:
    """수학적 최소 표기 — 값의 크기를 바꾸지 않는 후행 0을 뗀다.

    `TECH_SPEC §1.2.1` 표기 조항 1. `normalize()`는 `249120000`을 `2.4912E+8`로
    만들므로 지수 표기를 되돌린다.
    """
    normalized = value.normalize()
    sign, digits, exponent = normalized.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return str(normalized)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "cii"

TARGETS = {
    "bulk_50000_hfo_2026.json": build_fixture_1,
    "rating_boundaries_bulk_2026.json": build_fixture_2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="tests/fixtures/cii/ 에 기록한다")
    args = parser.parse_args()

    raw = compute_layer1(WORKING_PRECISION)
    canonical = check_invariance()
    check_against_expected(canonical)
    precisions = " · ".join(str(WORKING_PRECISION + n) for n in (0, 10, 20))
    print(f"✓ 불변성 검사 통과 — prec {precisions}")
    print(f"✓ 정본값 {len(EXPECTED_CANONICAL)}개 재현 확인")

    for filename, builder in TARGETS.items():
        payload = json.dumps(builder(canonical, raw), ensure_ascii=False, indent=2) + "\n"
        if args.write:
            path = FIXTURE_DIR / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            print(f"✓ {path.relative_to(FIXTURE_DIR.parent.parent.parent)}")
        else:
            print(f"\n─── {filename}\n{payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
