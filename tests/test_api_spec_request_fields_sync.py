"""`API_SPEC` JSON 요청 본문 표 ↔ 서버 요청 스키마 (#1523).

## 왜 필요한가

`tests/test_api_spec_endpoints_sync.py`는 **엔드포인트 목록**만 대조하고 필드는 보지
않는다. 그 사이로 빠진 것이 `#1454`다 — 항로 비교 요청의 `destination_port_name`은
서버 스키마(`ScenarioCompareRequest`)에도 있고 `§5.1`의 요청 예시 JSON에도 있었는데,
**같은 절의 필드 표에는 줄이 없었다.** 표만 읽고 요청을 만드는 사람은 그 필드를 알 길이
없고, 문서는 두 판을 자기와 어긋난 채 지났다. `#1454`를 처리한 PR `#1506`이 줄을 넣으며
*"이 가드가 없어 빠진 채 남아 있었다"* 고 적었고, 그것이 이 파일이다.

## 무엇을 대조하나 — 양방향 · 필수 여부까지

======================================  =====================================
 표에만 있음 (명세했는데 스키마가 모른다)   `extra="forbid"`라 보내면 **422**
 스키마에만 있음 (받는데 안 적었다)        `#1454`의 형태 — 문서만 읽으면 못 쓴다
 필수 여부가 다름                          「문서대로 보냈는데 거절됐다」
======================================  =====================================

필수 열의 **「조건부」는 스키마의 선택 필드와 짝**이다(결정요청 v6 `D-25`). 스키마가
조건부 필드를 필수로 선언하는 일은 없고, 조건 판정(「거리가 없으면 좌표 4개」 같은 것)은
서비스 코드의 몫이라 여기서 흉내 내지 않는다. **여기 적힌 표기 밖의 토큰은 실패다** —
새 표기가 조용히 「선택」으로 읽히면 필수 필드가 검사 없이 지나간다.

중첩 모델(`fuel_uses[]` · `adjustments[]` · `prices.*`)은 스키마를 따라 끝까지 편다.
`#1523` 첫 실행에서 `§2.10`이 `fuel_uses[].fuel_ton` 한 줄만 적고 `consumer_type`·
`fuel_type`(둘 다 필수)을 빠뜨린 것이 이 규칙으로 잡혔다.

## 표가 없는 절

요청 예시 JSON만 있는 절(`§2.3`·`§2.13`·`§3.3`·`§3.5`·`§3.6`)은 **키 집합**만 대조한다 —
예시는 필수 여부를 말하지 않는다. 「§X와 같되 전부 선택」으로 적은 PATCH 절은 그 문장
자체를 단언한다. 인증 엔드포인트(`§1.2`)는 스키마는 있으나 표도 예시도 없어 후속 이슈로
남긴다 — 그 목록을 여기 고정해 두어, 새 스키마가 생기면 표를 적거나 목록에 사유를 적어야
한다.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import re
from pathlib import Path
from types import UnionType
from typing import Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from cii_platform.api import schemas as schemas_package
from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.schemas.auth import (
    LoginRequest,
    MeUpdateRequest,
    PasswordChangeRequest,
    RoleUpdateRequest,
    SignupRequest,
    TourLoginRequest,
)
from cii_platform.api.schemas.auth_tokens import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    VerifyEmailConfirmRequest,
    VerifyEmailRequest,
)
from cii_platform.api.schemas.chat import ChatRequest
from cii_platform.api.schemas.fleet_reduction import (
    ReductionPlanRequest,
    ReductionPlanSaveRequest,
)
from cii_platform.api.schemas.not_underway import (
    NotUnderwayFuelUseCreateRequest,
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.schemas.scenario_compare import (
    ScenarioAdoptRequest,
    ScenarioCompareRequest,
)
from cii_platform.api.schemas.vessel import (
    VesselCreateRequest,
    VesselPositionUpdateRequest,
    VesselUpdateRequest,
)
from cii_platform.api.schemas.voyage import (
    VoyageActualsRequest,
    VoyageCreateRequest,
    VoyageTransitionRequest,
    VoyageUpdateRequest,
)
from cii_platform.api.schemas.voyage_cii import VoyageCiiRequest

_SPEC = Path(__file__).resolve().parents[1] / "API_SPEC.md"

#: 필드 경로 — `fuel_uses[].fuel_ton` → ``("fuel_uses", "fuel_ton")``.
FieldPath = tuple[str, ...]

#: 필수 열의 표기 → 뜻. **여기 없는 표기는 실패다** (모듈 docstring).
REQUIRED_TOKENS: dict[str, bool] = {
    "Y": True,
    "✅": True,
    "N": False,
    "아니오": False,
    "—": False,
    "조건부": False,
}

#: 「필드·필수」 열이 있는 요청 표 → 요청 스키마. 파일 업로드 표(`§7.5`·`§8.2`)는
#: multipart라 JSON 스키마가 없어 대상이 아니다.
TABLES: dict[str, type[BaseModel]] = {
    "2.6": VesselPositionUpdateRequest,
    "2.10": NotUnderwayPeriodCreateRequest,
    "2.17.1": ReductionPlanRequest,
    "4.1": VoyageCiiRequest,
    "5.1": ScenarioCompareRequest,
    "5.2": ScenarioAdoptRequest,
    "6.1": AnnualSimulationRequest,
    "15.1": ChatRequest,
}

#: `#1523` 시점 실측 행 수. 파싱이 깨져 0행이 되면 아래 대조가 「빈 것끼리 같다」로
#: 통과하므로 하한을 둔다 — 행을 지우는 돌연변이도 여기서 먼저 걸린다.
MIN_ROWS: dict[str, int] = {
    "2.6": 4,
    "2.10": 12,
    "2.17.1": 7,
    "4.1": 9,
    "5.1": 14,
    "5.2": 5,
    "6.1": 9,
    "15.1": 3,
}

#: 표 대신 요청 예시 JSON만 있는 절 → 스키마. 키 집합만 대조한다.
EXAMPLES: dict[str, type[BaseModel]] = {
    "2.3": VesselCreateRequest,
    "2.13": NotUnderwayFuelUseCreateRequest,
    "3.3": VoyageCreateRequest,
    "3.5": VoyageTransitionRequest,
    "3.6": VoyageActualsRequest,
}

#: 「§X의 필드와 같되 전부 선택」으로 적은 PATCH 절 → (스키마, 기준 스키마, 빠지는 필드).
PATCH_PROSE: dict[str, tuple[type[BaseModel], type[BaseModel], frozenset[str]]] = {
    # §2.4 — 「§2.3의 모든 필드는 optional. `imo_number`는 변경 불가」
    "2.4": (VesselUpdateRequest, VesselCreateRequest, frozenset({"imo_number"})),
    # §2.11 — 「모든 필드가 optional」. 연료는 §2.13으로 붙이므로 본문에 없다.
    "2.11": (
        NotUnderwayPeriodUpdateRequest,
        NotUnderwayPeriodCreateRequest,
        frozenset({"fuel_uses"}),
    ),
    # §3.4 — 「대상 필드는 §3.3 요청 본문과 같으므로」. 계획 연료(`fuel_uses`)는 PATCH로
    # 바꾸지 않는다 — 스키마에 없다. 문장이 그 예외를 적지 않은 것은 `#1523` 보고에 남겼다.
    "3.4": (VoyageUpdateRequest, VoyageCreateRequest, frozenset({"fuel_uses"})),
}

#: 스키마는 있으나 `§1.2`에 필드 표도 예시도 없는 인증 요청 — 후속 이슈 대상.
#: 여기서 빼려면 표를 적고 ``TABLES``로 옮긴다.
NO_TABLE_YET: frozenset[type[BaseModel]] = frozenset(
    {
        SignupRequest,
        LoginRequest,
        TourLoginRequest,
        PasswordChangeRequest,
        MeUpdateRequest,
        RoleUpdateRequest,
        VerifyEmailRequest,
        VerifyEmailConfirmRequest,
        PasswordResetRequest,
        PasswordResetConfirmRequest,
    }
)


# ── 문서 읽기 ─────────────────────────────────────────────────────────────────


def section(text: str, number: str) -> str:
    """`§number` 제목부터 같은 급 이상의 다음 제목 전까지."""
    heading = re.search(rf"^(#{{2,4}}) {re.escape(number)}\b.*$", text, re.M)
    assert heading, f"API_SPEC에 §{number} 제목이 없다"
    level = len(heading.group(1))
    rest = text[heading.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _cells(line: str) -> list[str]:
    """표 한 줄의 칸. `string \\| null`처럼 **이스케이프한 파이프는 칸을 가르지 않는다.**"""
    cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _path(name: str) -> FieldPath:
    """`fuel_uses[].fuel_ton` · `prices.charter_usd_per_day` → 경로."""
    return tuple(part.removesuffix("[]") for part in name.split("."))


def required_flag(token: str) -> bool:
    """필수 열 한 칸 → 필수 여부. 모르는 표기는 **조용히 선택으로 읽지 않는다.**"""
    if token not in REQUIRED_TOKENS:
        raise AssertionError(
            f"필수 열의 표기 「{token}」를 모른다. 뜻을 정해 REQUIRED_TOKENS에 적어야 한다"
        )
    return REQUIRED_TOKENS[token]


def field_table(text: str) -> dict[FieldPath, bool | None]:
    """절 원문에서 첫 「필드·필수」 표를 읽는다 → ``{경로: 필수 여부}``.

    한 칸에 이름이 둘이면(`lat` / `lon`) 둘 다 행이다. 하위 행(`prices.x`)만 있고 상위
    행이 없는 경로는 ``None``으로 넣는다 — 「표에 있다」로 치되 필수 여부는 모른다.
    """
    lines = text.splitlines()
    headers = [
        (index, _cells(line))
        for index, line in enumerate(lines)
        if line.startswith("|") and {"필드", "필수"} <= set(_cells(line))
    ]
    if not headers:
        raise AssertionError("「필드」·「필수」 열이 있는 표가 없다")

    start, header = headers[0]
    field_col, required_col = header.index("필드"), header.index("필수")
    rows: dict[FieldPath, bool | None] = {}
    for line in lines[start + 2 :]:  # 구분선(`|---|`)을 건너뛴다
        if not line.startswith("|"):
            break
        cells = _cells(line)
        flag = required_flag(cells[required_col])
        for name in re.findall(r"`([^`]+)`", cells[field_col]):
            path = _path(name)
            rows[path] = flag
            for depth in range(1, len(path)):
                rows.setdefault(path[:depth], None)
    return rows


def example_keys(text: str) -> set[FieldPath]:
    """절의 첫 ```json 블록의 키 경로. 배열은 첫 원소의 모양으로 읽는다."""
    block = re.search(r"```json\n(.*?)```", text, re.S)
    assert block, "```json 블록이 없다"
    return _flatten(json.loads(block.group(1)))


def _flatten(obj: dict, prefix: FieldPath = ()) -> set[FieldPath]:
    keys: set[FieldPath] = set()
    for key, value in obj.items():
        path = (*prefix, key)
        keys.add(path)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            keys |= _flatten(value[0], path)
        elif isinstance(value, dict):
            keys |= _flatten(value, path)
    return keys


# ── 스키마 읽기 ───────────────────────────────────────────────────────────────


def _nested_model(annotation: object) -> type[BaseModel] | None:
    """`list[X]` · `X | None` · `X` 안의 BaseModel. `dict[str, Decimal]`은 아니다."""
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (list, Union, UnionType):
        for arg in get_args(annotation):
            found = _nested_model(arg)
            if found is not None:
                return found
    return None


def schema_fields(model: type[BaseModel], prefix: FieldPath = ()) -> dict[FieldPath, bool]:
    """``{경로: 필수 여부}`` — 중첩 모델은 끝까지 편다."""
    fields: dict[FieldPath, bool] = {}
    for name, info in model.model_fields.items():
        path = (*prefix, name)
        fields[path] = info.is_required()
        nested = _nested_model(info.annotation)
        if nested is not None:
            fields.update(schema_fields(nested, path))
    return fields


def map_paths(model: type[BaseModel], prefix: FieldPath = ()) -> set[FieldPath]:
    """`dict[str, X]` 필드의 경로. 예시 JSON에서 그 아래 키(선박 ID · 유종 코드)는 **데이터**다."""
    paths: set[FieldPath] = set()
    for name, info in model.model_fields.items():
        path = (*prefix, name)
        if get_origin(info.annotation) is dict:
            paths.add(path)
        nested = _nested_model(info.annotation)
        if nested is not None:
            paths |= map_paths(nested, path)
    return paths


def example_fields(text: str, model: type[BaseModel]) -> set[FieldPath]:
    """예시 JSON의 키 중 **필드명인 것** — 맵 필드 아래의 데이터 키를 뺀다."""
    maps = map_paths(model)
    return {
        key
        for key in example_keys(text)
        if not any(
            len(key) > len(map_path) and key[: len(map_path)] == map_path for map_path in maps
        )
    }


def nested_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    """이 모델과 그 안에 든 모델 전부."""
    found = {model}
    for info in model.model_fields.values():
        nested = _nested_model(info.annotation)
        if nested is not None:
            found |= nested_models(nested)
    return found


# ── 대조 ─────────────────────────────────────────────────────────────────────


def mismatches(table: dict[FieldPath, bool | None], schema: dict[FieldPath, bool]) -> list[str]:
    """어긋난 곳의 목록. 비어 있으면 같다."""
    found: list[str] = []
    for path in sorted(table.keys() - schema.keys()):
        found.append(f"표에만 있다: {'.'.join(path)}")
    for path in sorted(schema.keys() - table.keys()):
        found.append(f"스키마에만 있다: {'.'.join(path)}")
    for path in sorted(table.keys() & schema.keys()):
        flag = table[path]
        if flag is None:
            if schema[path]:
                found.append(f"필수인데 표에 자기 행이 없다(하위 행만 있다): {'.'.join(path)}")
        elif flag != schema[path]:
            found.append(
                f"필수 여부가 다르다: {'.'.join(path)} — 표 {'필수' if flag else '선택'} / "
                f"스키마 {'필수' if schema[path] else '선택'}"
            )
    return found


def _spec() -> str:
    return _SPEC.read_text(encoding="utf-8")


# ── 실제 문서 ─────────────────────────────────────────────────────────────────


def test_every_table_is_parsed_at_all() -> None:
    """표를 읽지 못하면 아래 대조가 **「빈 것끼리 같다」로 통과**한다."""
    text = _spec()
    assert set(TABLES) == set(MIN_ROWS)
    for number, minimum in MIN_ROWS.items():
        rows = {
            path: flag
            for path, flag in field_table(section(text, number)).items()
            if flag is not None
        }
        assert len(rows) >= minimum, f"§{number} 표를 읽지 못했다: {len(rows)}행 (하한 {minimum})"


@pytest.mark.parametrize("number", sorted(TABLES))
def test_request_table_matches_schema(number: str) -> None:
    """`§number` 필드 표 ↔ 요청 스키마 — 양방향 · 필수 여부 (`#1523`)."""
    table = field_table(section(_spec(), number))
    schema = schema_fields(TABLES[number])

    found = mismatches(table, schema)
    assert not found, (
        f"API_SPEC §{number} 요청 표가 {TABLES[number].__name__}와 어긋납니다. "
        "틀린 쪽을 고치세요(표면 정본 변경):\n" + "\n".join(f"  {line}" for line in found)
    )


@pytest.mark.parametrize("number", sorted(EXAMPLES))
def test_example_only_section_lists_every_field(number: str) -> None:
    """표가 없는 절의 예시 JSON은 **스키마 필드 전부**를 보인다 (필수 여부는 대조하지 않는다)."""
    keys = example_fields(section(_spec(), number), EXAMPLES[number])
    schema = set(schema_fields(EXAMPLES[number]))

    assert keys == schema, (
        f"API_SPEC §{number} 요청 예시가 {EXAMPLES[number].__name__}와 어긋납니다:\n"
        + "\n".join(f"  예시에만 있다: {'.'.join(p)}" for p in sorted(keys - schema))
        + "\n".join(f"  스키마에만 있다: {'.'.join(p)}" for p in sorted(schema - keys))
    )


@pytest.mark.parametrize("number", sorted(TABLES))
def test_example_next_to_a_table_uses_only_schema_fields(number: str) -> None:
    """표 옆의 예시 JSON은 일부만 보여도 되지만 **스키마에 없는 키를 보이면 안 된다.**

    `#1454`는 예시가 표보다 앞서 있던 경우다. 반대로 예시만 낡아 지운 필드를 보이면
    그대로 따라 보낸 요청이 `extra="forbid"`에 422로 끝난다.
    """
    text = section(_spec(), number)
    if "```json" not in text:
        pytest.skip(f"§{number}에는 요청 예시가 없다")
    keys = example_fields(text, TABLES[number])
    schema = set(schema_fields(TABLES[number]))

    stray = sorted(keys - schema)
    assert not stray, f"API_SPEC §{number} 예시에 스키마가 모르는 키가 있습니다: " + ", ".join(
        ".".join(p) for p in stray
    )


@pytest.mark.parametrize("number", sorted(PATCH_PROSE))
def test_patch_prose_holds(number: str) -> None:
    """「§X의 필드와 같되 전부 선택」이라는 문장이 스키마에서 참인가."""
    model, base, excluded = PATCH_PROSE[number]
    fields = schema_fields(model)
    expected = {path for path in schema_fields(base) if path[0] not in excluded}

    assert set(fields) == expected, f"§{number}: 필드 집합이 문장과 다르다"
    still_required = sorted(".".join(p) for p, flag in fields.items() if flag)
    assert not still_required, f"§{number}: 「전부 선택」인데 필수가 있다: {still_required}"


def test_save_request_is_evaluate_request_plus_plan_name() -> None:
    """`§2.17.2` — 「§2.17.1 본문 + `plan_name`」."""
    assert set(schema_fields(ReductionPlanSaveRequest)) == set(
        schema_fields(ReductionPlanRequest)
    ) | {("plan_name",)}
    assert ReductionPlanSaveRequest.model_fields["plan_name"].is_required()


def test_every_request_schema_is_covered() -> None:
    """`api/schemas/*`의 모든 모델이 위 어느 대조에든 든다.

    새 요청 스키마를 만들면 표를 적어 ``TABLES``에 넣거나, 사유를 적어 ``NO_TABLE_YET``에
    넣어야 한다 — 둘 다 없으면 여기서 멈춘다. 반대로 스키마를 지웠는데 목록에 남아 있으면
    import에서 먼저 죽는다.
    """
    defined: set[type[BaseModel]] = set()
    for info in pkgutil.iter_modules(schemas_package.__path__):
        module = importlib.import_module(f"{schemas_package.__name__}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                defined.add(obj)

    covered: set[type[BaseModel]] = set(NO_TABLE_YET) | {ReductionPlanSaveRequest}
    for model in [*TABLES.values(), *EXAMPLES.values(), *(m for m, _, _ in PATCH_PROSE.values())]:
        covered |= nested_models(model)

    assert defined, "요청 스키마를 하나도 찾지 못했다"
    uncovered = sorted(m.__name__ for m in defined - covered)
    assert not uncovered, "표·예시·후속 목록 어디에도 없는 요청 스키마: " + ", ".join(uncovered)
    stale = sorted(m.__name__ for m in covered - defined)
    assert not stale, "패키지에 없는 모델을 대조 목록이 가리킨다: " + ", ".join(stale)


# ── 돌연변이 — 순수 함수로 잠근다 ────────────────────────────────────────────

_HEADER = "| 필드 | 타입 | 필수 | 설명 |\n|---|---|---|---|\n"


def _table(*rows: str) -> str:
    return "#### 요청\n\n" + _HEADER + "".join(f"{row}\n" for row in rows) + "\n다음 문단.\n"


class _Item(BaseModel):
    fuel_type: str
    fuel_ton: int


class _Model(BaseModel):
    vessel_id: str
    lat: float | None = None
    lon: float | None = None
    fuel_uses: list[_Item] = []


_FULL = _table(
    "| `vessel_id` | string | Y | 대상 |",
    "| `lat` / `lon` | number \\| null | 조건부 | 한 칸에 둘 |",
    "| `fuel_uses` | array | N | 목록 |",
    "| `fuel_uses[].fuel_type` | string | Y | |",
    "| `fuel_uses[].fuel_ton` | int | Y | |",
)


def test_matching_table_has_no_mismatch() -> None:
    """이스케이프한 파이프(`number \\| null`)와 한 칸의 두 이름(`lat` / `lon`)을 읽는다."""
    assert mismatches(field_table(_FULL), schema_fields(_Model)) == []


def test_a_row_missing_from_the_table_fails() -> None:
    """`#1454`의 형태 — 스키마는 받는데 표에 줄이 없다."""
    table = _table(
        "| `vessel_id` | string | Y | 대상 |",
        "| `lat` / `lon` | number \\| null | 조건부 | |",
        "| `fuel_uses` | array | N | |",
        "| `fuel_uses[].fuel_ton` | int | Y | |",
    )
    assert mismatches(field_table(table), schema_fields(_Model)) == [
        "스키마에만 있다: fuel_uses.fuel_type"
    ]


def test_a_field_added_to_the_schema_fails() -> None:
    """스키마에 필드를 더하고 표를 안 고치면 걸린다."""

    class _Wider(_Model):
        notes: str | None = None

    assert mismatches(field_table(_FULL), schema_fields(_Wider)) == ["스키마에만 있다: notes"]


def test_a_field_only_in_the_table_fails() -> None:
    """표에만 있는 필드 — `extra="forbid"`라 보내면 422다."""
    table = _FULL.replace(
        "| `fuel_uses` | array |", "| `speed_knots` | number | N | |\n| `fuel_uses` | array |"
    )
    assert mismatches(field_table(table), schema_fields(_Model)) == ["표에만 있다: speed_knots"]


def test_a_required_flag_mismatch_fails() -> None:
    table = _FULL.replace("| `vessel_id` | string | Y |", "| `vessel_id` | string | N |")
    assert mismatches(field_table(table), schema_fields(_Model)) == [
        "필수 여부가 다르다: vessel_id — 표 선택 / 스키마 필수"
    ]


def test_conditional_pairs_with_optional_only() -> None:
    """「조건부」는 선택 필드와 짝이다 — 필수 필드에 적으면 어긋남이다 (`D-25`)."""
    table = _FULL.replace("| `vessel_id` | string | Y |", "| `vessel_id` | string | 조건부 |")
    assert mismatches(field_table(table), schema_fields(_Model)) == [
        "필수 여부가 다르다: vessel_id — 표 선택 / 스키마 필수"
    ]


def test_an_unknown_required_token_fails_loudly() -> None:
    """모르는 표기를 「선택」으로 읽으면 필수 필드가 검사 없이 지나간다."""
    table = _FULL.replace("| `vessel_id` | string | Y |", "| `vessel_id` | string | 필수 |")
    with pytest.raises(AssertionError, match="「필수」"):
        field_table(table)


def test_a_required_parent_needs_its_own_row() -> None:
    """하위 행(`x.y`)만으로 상위 `x`를 표에 있다고 치되, 상위가 필수면 자기 행이 있어야 한다."""

    class _Prices(BaseModel):
        fuel: int = 0

    class _OptionalParent(BaseModel):
        prices: _Prices = _Prices()

    class _RequiredParent(BaseModel):
        prices: _Prices

    table = field_table(_table("| `prices.fuel` | int | N | |"))
    assert mismatches(table, schema_fields(_OptionalParent)) == []
    assert mismatches(table, schema_fields(_RequiredParent)) == [
        "필수인데 표에 자기 행이 없다(하위 행만 있다): prices"
    ]


def test_a_section_without_a_field_table_fails() -> None:
    with pytest.raises(AssertionError, match="표가 없다"):
        field_table("#### 요청\n\n| 규칙 | 위반 시 |\n|---|---|\n| a | b |\n")


def test_section_stops_at_the_next_heading_of_same_level() -> None:
    """`### 2.1`이 `### 2.10`을 삼키지 않고, `#### 2.17.1`이 `#### 2.17.2`에서 끝난다."""
    text = "### 2.1 A\n\nx\n\n#### 2.1.1 sub\n\ny\n\n### 2.10 B\n\nz\n"
    assert section(text, "2.1").strip() == "x\n\n#### 2.1.1 sub\n\ny"
    assert section(text, "2.10").strip() == "z"
    text = "#### 2.17.1 A\n\nx\n\n#### 2.17.2 B\n\ny\n\n### 3 C\n"
    assert section(text, "2.17.1").strip() == "x"


def test_example_keys_follow_nested_shapes() -> None:
    text = '```json\n{"a": 1, "items": [{"b": 2}], "obj": {"c": {"d": 3}}}\n```\n'
    assert example_keys(text) == {
        ("a",),
        ("items",),
        ("items", "b"),
        ("obj",),
        ("obj", "c"),
        ("obj", "c", "d"),
    }


def test_map_entries_in_an_example_are_data_not_fields() -> None:
    """`prices.fuel_usd_per_ton.HFO`의 `HFO`는 필드가 아니다 — 맵 필드 자체는 남는다."""

    class _Prices(BaseModel):
        fuel_usd_per_ton: dict[str, int] = {}

    class _Plan(BaseModel):
        prices: _Prices = _Prices()
        note: str | None = None

    text = '```json\n{"prices": {"fuel_usd_per_ton": {"HFO": 600}}, "note": "x"}\n```\n'
    assert example_fields(text, _Plan) == {("prices",), ("prices", "fuel_usd_per_ton"), ("note",)}
