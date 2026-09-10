#!/usr/bin/env python3
"""지정 서체를 자체 호스팅용 woff2로 만든다 (``#925``).

## 왜 스크립트인가

`DESIGN_SYSTEM §3`이 정한 서체(**Noto Sans KR** · **Noto Sans Mono**)가 저장소에
없었고 CDN도 쓸 수 없다 — `#791`이 **「인터넷이 없다고 가정한 경로가 반드시 함께
있어야 한다」**로 못 박는다. 그래서 파일을 저장소에 넣는데, **넣은 파일이 어떻게
만들어졌는지 적어 두지 않으면 다시 만들 수 없다.**

굵기가 바뀌거나(`§3`이 400·500을 쓴다) 서브셋 범위를 넓혀야 할 때 이 파일을 고쳐
다시 돌린다. 결과물은 결정적이다 — 같은 원본·같은 범위면 같은 바이트가 나온다.

## 무엇을 고르지 않았는가

- **Google 서브셋 전량**(웨이트당 124조각 · 2웨이트 248파일 ≈ 10MB) — 브라우저가
  필요한 조각만 받는 이점이 있으나 저장소에 248개가 쌓인다
- **실사용 문자만 서브셋**(≈100KB) — **사용자 데이터의 글자가 빠진다.** 선박명·항구명은
  런타임에 들어오므로 저장소 문자열에서 뽑을 수 없다. 데모 시드에 한글 선박명이 있다

**한글 전체 서브셋**을 고른 이유는 파일이 굵기당 하나로 끝나면서 **사용자가 입력할 수 있는
한글이 전부 덮이기** 때문이다.

## 쓰는 법

    uv run --with "fonttools[woff]" --with brotli python scripts/build_fonts.py

원본은 내려받아 ``build/fonts/`` 에 두고, 결과만 ``frontend/public/fonts/`` 로 옮긴다.
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

#: `DESIGN_SYSTEM §3` — 「굵기는 400·500만 쓴다」. 700은 v1.2에서 낮췄다.
WEIGHTS = (400, 500)

#: 한글 전체 + 라틴 + 문장부호.
#:
#: `AC00-D7A3`(음절 11,172자)이 부피의 대부분이다. 자모(`1100-11FF`)와 호환 자모
#: (`3130-318F`)를 함께 넣는 것은 **조합형으로 들어오는 입력**과 자모 단독 표기를
#: 위해서다. `3000-303F`는 「」·〔〕 같은 이 저장소가 실제로 쓰는 부호다.
KOREAN_RANGES = (
    "U+0020-007E",  # 기본 라틴
    "U+00A0-00FF",  # 라틴-1 보충 (°, ±, ×)
    "U+2000-206F",  # 일반 문장부호 (—, ·, ", ')
    "U+20A0-20BF",  # 통화 (₩)
    "U+2190-21FF",  # 화살표 (→)
    "U+25A0-25FF",  # 도형 (■, ●)
    "U+3000-303F",  # CJK 부호 (「」, 〔〕)
    "U+1100-11FF",  # 한글 자모
    "U+3130-318F",  # 호환 자모
    "U+AC00-D7A3",  # 한글 음절
    "U+FF00-FFEF",  # 전각
)

#: mono는 **IMO 번호·좌표 전용**이다 (`§3`). 한글이 들어갈 일이 없다.
MONO_RANGES = (
    "U+0020-007E",
    "U+00A0-00FF",
    "U+2000-206F",
    "U+00B0",  # 도 기호 — 좌표에 쓴다
)


def build(src: Path, out_dir: Path, family: str, ranges: tuple[str, ...]) -> list[Path]:
    """가변 폰트를 굵기별 정적 인스턴스로 뽑아 서브셋한 woff2를 만든다."""
    made: list[Path] = []
    for weight in WEIGHTS:
        font = TTFont(src)
        # 가변축을 굵기 하나로 고정한다. 가변 폰트를 그대로 내보내면 굵기 전 구간의
        # 글리프 보간 데이터가 따라와 파일이 몇 배로 커진다.
        static = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)

        # ⚠️ **인스턴싱 결과를 바로 서브셋하면 깨진다.** 지연 로딩 테이블(`hdmx` 등)이
        # 인스턴싱 전 글리프 이름을 들고 있어 `KeyError: 'uni2062'`로 죽는다.
        # 한 번 직렬화했다가 다시 읽으면 그 참조가 정리된다.
        buffer = BytesIO()
        static.save(buffer)
        buffer.seek(0)
        static = TTFont(buffer)

        options = subset.Options()
        options.flavor = "woff2"
        # 이름 레코드를 남긴다 — 폰트 파일만 보고 무엇인지 알 수 있어야 한다.
        options.name_IDs = ["*"]
        # `.notdef`를 비우지 않는다. 서브셋 밖 글자가 들어오면 빈칸이 아니라
        # 두부(□)로 보여야 **빠졌다는 사실이 드러난다.**
        options.notdef_outline = True
        # 레이아웃 기능은 기본값을 쓴다. `["*"]`로 전부 남기면 이 서체가 쓰지 않는
        # CJK 전용 기능까지 따라와 40KB가 늘고, 한글 조합·커닝은 기본값에 포함된다.

        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=subset.parse_unicodes(",".join(ranges)))
        subsetter.subset(static)

        out = out_dir / f"{family}-{weight}.woff2"
        static.flavorData = None
        static.save(out)
        made.append(out)
    return made


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    src_dir = root / "build" / "fonts"
    out_dir = root / "frontend" / "public" / "fonts"
    out_dir.mkdir(parents=True, exist_ok=True)

    plan = [
        (src_dir / "NotoSansKR.ttf", "noto-sans-kr", KOREAN_RANGES),
        (src_dir / "NotoSansMono.ttf", "noto-sans-mono", MONO_RANGES),
    ]

    for src, family, ranges in plan:
        if not src.exists():
            print(f"원본이 없습니다: {src}", file=sys.stderr)
            print("  내려받는 곳은 이 파일 머리의 주석을 보세요.", file=sys.stderr)
            return 1
        for made in build(src, out_dir, family, ranges):
            print(f"{made.relative_to(root)}  {made.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
