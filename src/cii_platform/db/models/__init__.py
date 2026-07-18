"""SQLAlchemy ORM 모델.

DB_SCHEMA.md의 테이블에 대응하는 ORM 모델을 정의한다. DB 관련 코드를
``db`` 트리로 응집하기 위해 저장소(``db.repositories``)와 같은 레이어에 둔다.

``Base.metadata``는 ``alembic/env.py``의 ``target_metadata``에 연결되어
autogenerate(모델↔DB 비교)에 사용된다. 모델과 실제 DB의 일치(zero drift)는
``tests/test_orm_schema_sync.py``가 CI에서 상시 검증한다.

새 모델 추가 시 이 파일에서 import해야 ``Base.metadata``에 등록된다.

계층 규칙은 TECH_SPEC §16 참조.
"""

from cii_platform.db.models.base import Base
from cii_platform.db.models.calculation_run import CalculationRun
from cii_platform.db.models.fuel_type import FuelType
from cii_platform.db.models.regulation_year import RegulationYear
from cii_platform.db.models.simulation_snapshot import SimulationSnapshot
from cii_platform.db.models.vessel import Vessel
from cii_platform.db.models.voyage import Voyage
from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse
from cii_platform.db.models.voyage_scenario import VoyageScenario

__all__ = [
    "Base",
    "CalculationRun",
    "FuelType",
    "RegulationYear",
    "SimulationSnapshot",
    "Vessel",
    "Voyage",
    "VoyageFuelUse",
    "VoyageScenario",
]
