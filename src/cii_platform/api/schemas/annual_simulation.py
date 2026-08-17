"""연간 시뮬레이션 요청 스키마 (API_SPEC §6.1, #64).

요청만 Pydantic으로 정의한다. 응답은 서비스가 만든 dict를 그대로 내보낸다
(``schemas/voyage.py``와 같은 규약).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnnualSimulationRequest(BaseModel):
    """``POST /api/v1/annual-simulations`` 요청 본문."""

    model_config = ConfigDict(extra="forbid")

    vessel_id: UUID
    regulation_year: Annotated[int, Field(ge=2000, le=2100)]
    #: A~D. **E는 거부**한다 (`PRD §12.8`) — 검증은 서비스가 하고, 여기서는 길이만 본다.
    #: 열거값을 두 곳에 두면 갈리므로 정본 하나(`services.annual_simulation`)만 둔다.
    target_rating: Annotated[str, Field(min_length=1, max_length=1)]
    simulation_runs: Annotated[int, Field(ge=1_000, le=10_000)] = 5_000
    #: `API_SPEC §6.1` [ORACLE-S-3] — 0 ~ 2^128−1. **JSON int는 2^53까지만 안전**하므로
    #: 큰 값은 문자열로 보낸다. 둘 다 받아 int로 정규화한다.
    random_seed: int | str | None = None
    distribution_profile: Annotated[str, Field(max_length=30)] = "DEFAULT"
    as_of: datetime | None = None

    @field_validator("random_seed")
    @classmethod
    def _normalize_seed(cls, value: int | str | None) -> int | None:
        """문자열 seed를 int로. 범위를 벗어나면 거부한다.

        조용히 잘라내지 않는다 — 잘린 seed로 돌리면 사용자가 적어 둔 seed와 실제
        사용된 seed가 달라지고, 「이 seed로 다시 실행」이 다른 결과를 낸다.
        """
        if value is None:
            return None
        try:
            seed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("random_seed는 정수여야 합니다.") from exc
        if not 0 <= seed < 2**128:
            raise ValueError("random_seed는 0 이상 2^128 미만이어야 합니다.")
        return seed
