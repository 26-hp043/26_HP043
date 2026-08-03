"""파라미터·입력값 content hash (#42).

계산 결과의 재현성 단위를 정의한다. TECH_SPEC §5.4 재현성 계약 1항 — "동일
``input_hash`` + 동일 ``parameter_hash`` + 동일 ``model_version`` → 항상 동일 결과".

구현은 TECH_SPEC §5.1.2(직렬화) · §5.2(parameter hash) · §5.3(input hash) 원문을
그대로 따른다. 이슈 본문 힌트의 ``str(Decimal.normalize())`` 방식은 채택하지 않았다 —
``normalize()``가 trailing zero를 지수 표기로 바꾸기 때문에 seed의 ``a_decimal`` 6행
(``14405E7`` · ``14479E10`` · ``14779E10`` · ``4600`` · ``330`` · ``930``)에서 정본과
다른 해시가 나온다. 경위는 #42 코멘트에 남겼다.

직렬화 규칙 (§5.1.1):

* 키는 UTF-8 바이트순 정렬, 공백 없음(minified), UTF-8 인코딩
* 모든 수치는 Decimal 문자열로 변환. ``float``는 **금지**(``TypeError``) [ORACLE-M-4]
* Decimal은 ``normalize()`` 후 고정 소수점 표기 [ORACLE-C-2]
* ``None``은 JSON ``null``로 직렬화하며 필드를 생략하지 않는다 [ORACLE-M-3]
"""

import hashlib
import json
from decimal import Decimal
from typing import Any

#: ``input_hash`` 대상 필드와 그 순서 (TECH_SPEC §5.3).
#:
#: 정본은 이 목록을 :func:`compute_input_hash` 함수 안에 두지만, 테스트로 잠그기 위해
#: 모듈 상수로 꺼냈다(값·순서는 정본 그대로). 이 목록이 바뀌면 이미 저장된 모든
#: ``input_hash``가 무효가 되고, §5.4 재현성 계약 2항이 이 목록을 전제로 서 있다.
INPUT_FIELDS: tuple[str, ...] = (
    "vessel_id",
    "regulation_year",
    "ship_type",
    "transport_capacity",  # [EXT-P0-1] attained CII의 W에 쓰는 실제 DWT/GT
    "reference_capacity",  # [EXT-P0-1] CII_ref용 capacity_rule 해석값
    "distance_nm",
    "speed_kn",
    "fuel_uses",  # [{fuel_type, fuel_ton, cf}]
    "weather_model",
    "weather_factor",  # [ORACLE-S-5] hash 전 반드시 확정
)

#: ``weather_model = NONE`` 또는 미확정 시의 기본 기상 보정 계수 (TECH_SPEC §5.3).
DEFAULT_WEATHER_FACTOR = Decimal("1.0")

#: 해시 문자열 접두사. DB_SCHEMA §2.5 ``chk_input_hash_format`` 제약과 같은 형식이다.
HASH_PREFIX = "sha256:"


def _decimal_to_canonical_str(d: Decimal) -> str:
    """Decimal을 canonical 문자열로 변환한다 (TECH_SPEC §5.1.2 [ORACLE-C-2]).

    ``normalize()``로 trailing zero를 제거한 뒤 고정 소수점으로 편다.
    ``normalize()``만 쓰면 ``Decimal("4600")``이 ``"4.6E+3"``이 되어, 같은 값이
    표기에 따라 다른 해시를 낸다.
    """
    normalized = d.normalize()
    # format 'f' avoids scientific notation (e.g., 1.4405E+11 → 144050000000)
    s = format(normalized, "f")
    # Remove trailing .0 for integer values
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def canonical_json(obj: Any) -> str:
    """결정적 JSON 직렬화 (TECH_SPEC §5.1.2).

    ``int``·``bool``·``str``은 그대로 통과한다. 즉 ``{"year": 2026}``과
    ``{"year": "2026"}``은 서로 다른 해시를 낸다. ``float``만 막는 이유는 값의 표현이
    결정적이지 않기 때문이며, ``int``는 표현이 결정적이라 재현성 계약상 문제가 없다.
    "같은 논리값을 두 방식으로 표현할 수 있다"는 호출부 규약 문제이고, §5.2.1
    ``parameters_used`` 스키마가 모든 값을 문자열로 규정하고 있다.

    :raises TypeError: ``float``가 포함된 경우 (중첩 dict·list 포함) [ORACLE-M-4]
    """

    def convert(o: Any) -> Any:
        if isinstance(o, Decimal):
            return _decimal_to_canonical_str(o)
        if isinstance(o, float):
            # [ORACLE-M-4] float는 허용하지 않음 — Decimal 사용 강제
            raise TypeError(f"float not allowed in canonical_json: {o}. Use Decimal instead.")
        if isinstance(o, dict):
            return {k: convert(v) for k, v in sorted(o.items())}
        if isinstance(o, (list, tuple)):
            return [convert(item) for item in o]
        if o is None:
            return None  # [ORACLE-M-3] JSON null
        return o

    return json.dumps(
        convert(obj),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sha256_of(canonical: str) -> str:
    """canonical 문자열의 SHA-256을 ``sha256:`` 접두사와 함께 반환한다."""
    return HASH_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_parameter_hash(parameters_used: dict) -> str:
    """해당 계산에 사용된 모든 규정 파라미터의 content hash (TECH_SPEC §5.2).

    입력 스키마는 §5.2.1을 따른다 — ``regulation_year`` · ``fuel_types`` ·
    ``reference_line`` · ``rating_boundary`` · ``parameter_source_version``.
    """
    return _sha256_of(canonical_json(parameters_used))


def compute_input_hash(calculation_input: dict) -> str:
    """계산 입력값의 content hash (TECH_SPEC §5.3).

    :data:`INPUT_FIELDS`에 있는 필드만 골라 해싱한다 — 요청에 딸려온 부수 필드가
    재현성 단위를 흔들지 않게 하기 위함이다. 목록에 없는 키는 무시하고, 목록에
    있으나 입력에 없는 키는 넣지 않는다(정본 §5.3의 ``if k in calculation_input``).

    ``weather_factor``는 해싱 **전에** 확정되어 있어야 한다 [ORACLE-S-5]. ``None``이면
    NONE 모델 기본값 ``Decimal("1.0")``으로 간주한다. 이 치환은 이 함수의 전처리이며,
    :func:`canonical_json`의 "``None`` → JSON ``null``" 규칙(§5.1.1 [ORACLE-M-3])과는
    다른 층이다 — 다른 필드의 ``None``은 그대로 ``null``로 남는다.

    기본값 적용은 **이 함수의 책임**이다. 호출부는 ``weather_factor``가 미확정이면
    ``None``을 그대로 넘긴다. 호출부에서 먼저 대입하면 같은 규약이 두 곳에 생긴다.
    """
    filtered: dict[str, Any] = {}
    for key in INPUT_FIELDS:
        if key in calculation_input:
            value = calculation_input[key]
            # [ORACLE-S-5] weather_factor가 None이면 기본값 사용
            if key == "weather_factor" and value is None:
                value = DEFAULT_WEATHER_FACTOR
            filtered[key] = value

    return _sha256_of(canonical_json(filtered))
