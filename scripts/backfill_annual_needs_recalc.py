#!/usr/bin/env python
"""저장 연간 실행의 낡음 표시 소급 처리 실행 스크립트 (#2373).

``python scripts/backfill_annual_needs_recalc.py``(미리 보기) 또는 ``--apply``로 실행한다.
대상 DB는 ``DATABASE_URL`` 환경변수를 따른다.

견주는 기준 · 견줄 수 없는 실행의 처리 · 적용 절차는 모두
``cii_platform.maintenance.annual_needs_recalc``에 있다 — 이 파일은 **editable 설치 없이도
돌아가게 해 주는 개발용 래퍼**일 뿐이다(``scripts/seed.py``와 같은 판). 프로덕션 이미지는 wheel만
설치해 ``scripts/``가 없으므로 운영 절차는
``python -m cii_platform.maintenance.annual_needs_recalc``를 쓴다.
실행 로직의 사본을 여기 두지 않는다 — 사본을 두면 한쪽만 고쳐지는 일이 생긴다(#234).
"""

import asyncio
import sys
from pathlib import Path

# src 레이아웃을 sys.path에 추가하여 editable 설치 없이도 import할 수 있게 한다
# (scripts/seed.py와 동일 정책).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cii_platform.maintenance.annual_needs_recalc import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
