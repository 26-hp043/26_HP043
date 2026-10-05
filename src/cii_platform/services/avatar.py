"""프로필 이미지 — 받은 바이트를 **다시 그린다** (`#2080`).

이 제품이 사용자가 올린 바이트를 남기는 첫 자리다. 종전 업로드 둘(규정 파라미터
적재 · 항차 CSV 가져오기)은 파싱하고 **버린다**.

## 왜 다시 그리는가 — 검사만 하지 않고

재인코딩 한 번이 네 가지를 함께 닫는다.

1. **EXIF가 떨어진다.** 휴대폰 사진에는 촬영 위치가 들어 있다. 검사만 하고 원본을
   저장하면 그 좌표가 DB에 남고, 내보내는 경로로 그대로 나간다.
2. **압축 폭탄이 걸린다.** 작은 파일이 거대한 픽셀로 펴지는 것은 바이트 상한으로
   막히지 않는다 — 디코드가 막는다.
3. **형식을 바이트가 말한다.** 확장자도 ``Content-Type``도 보지 않는다. 디코드가
   되면 그 형식이고, 안 되면 아니다.
4. **저장 크기가 고정된다.** `Base64Bytes`가 바이트를 4/3로 불리는데(`#2080`),
   들어오는 쪽이 열려 있으면 그 4/3도 열린 값이 된다.

## 받지 않는 것

**SVG를 받지 않는다.** 스크립트를 품을 수 있고, 우리가 그것을 내보내면 같은
출처에서 남의 스크립트가 도는 길이 된다. Pillow가 SVG를 열지 못하므로 규칙을
따로 적지 않아도 막히지만, **막히는 이유가 우연이 아니도록** 허용 형식을 닫힌
집합으로 적는다 — Pillow가 언젠가 SVG를 열게 되어도 이 집합이 막는다.
"""

from __future__ import annotations

import hashlib
import io

import anyio
import anyio.to_thread
from PIL import Image, ImageOps, UnidentifiedImageError

from cii_platform.errors import ValidationError

#: 받는 바이트의 상한. 휴대폰 사진 한 장이 넉넉히 들어오는 크기다.
#:
#: ⚠️ **디코드보다 먼저 본다.** 압축 폭탄은 바이트가 작고 픽셀이 크므로 이 상한으로는
#: 막히지 않지만, 반대로 **거대한 파일이 디코더에 들어가는 것**은 이 상한이 막는다.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

#: 저장하는 정사각 변 길이. 설정의 미리보기와 사이드바가 쓰는 가장 큰 자리의 두 배다.
AVATAR_SIZE = 256

#: 디코드를 허용하는 형식. **닫힌 집합이다** — 여기 없는 것은 열려도 받지 않는다.
#:
#: ``MPO``는 **JPEG다** (#2107). 휴대폰·카메라가 한 파일에 프레임을 둘 이상 담으면
#: (MPF — 깊이 지도·미리보기 등) Pillow가 형식을 ``MPO``로 읽는다. 사용자가 고른 것은
#: `.jpg` 사진 한 장이고, 첫 프레임이 그 사진이다 — 아래에서 다시 그릴 때 첫 프레임만 쓴다.
ACCEPTED_FORMATS: frozenset[str] = frozenset({"PNG", "JPEG", "WEBP", "MPO"})

#: 펴진 그림의 픽셀 상한 (압축 폭탄).
#:
#: Pillow의 기본값(약 1.79억)은 「경고」 기준이라 우리 기준보다 훨씬 느슨하다.
#: 프로필 사진에 4000만 화소가 필요할 이유가 없다.
MAX_PIXELS = 40_000_000

#: 내보낼 때 쓰는 MIME. 항상 이 하나다 — 저장하는 형식이 하나이기 때문이다.
AVATAR_MEDIA_TYPE = "image/webp"

TOO_LARGE_MESSAGE = "이미지가 너무 큽니다. 2MB 이하로 올려 주세요."
#: 픽셀 상한 초과 전용 (#2107). 이 파일은 **이미 2MB 아래다** — 「2MB 이하로」를 말하면
#: 사용자는 할 수 있는 일이 없다. 줄여야 하는 것은 용량이 아니라 가로·세로다.
TOO_MANY_PIXELS_MESSAGE = (
    "이미지의 가로·세로가 너무 큽니다. 가로×세로 4,000만 화소 이하로 줄여 올려 주세요."
)

#: 동시에 다시 그리는 수의 상한 (#2107).
#:
#: 다시 그리기는 CPU 작업이다 — 상한 안의 이미지 한 장이 1초를 넘긴다(6300×6300 PNG ·
#: 115KB · 실측 1.53초). 스레드로 내보내 이벤트 루프를 비워 두되, 그 스레드가 기본 풀을
#: 다 차지하지 않게 따로 센다. 비밀번호 해시(``auth/password``)·PDF(``reports/pdf``)와
#: 같은 방식이다.
MAX_CONCURRENT_RENDERS = 2

_render_limiter = anyio.CapacityLimiter(MAX_CONCURRENT_RENDERS)
UNREADABLE_MESSAGE = "이미지를 읽을 수 없습니다. PNG · JPEG · WebP 파일을 올려 주세요."


class AvatarTooLargeError(Exception):
    """바이트 상한 초과 — HTTP 413.

    `ValidationError`(422)와 가르는 이유는 **고칠 방법이 다르기** 때문이다. 형식이
    틀린 것은 다른 파일을 골라야 하지만, 큰 것은 같은 사진을 줄여도 된다.
    """

    def __init__(self, message: str = TOO_LARGE_MESSAGE) -> None:
        super().__init__(message)


def render_avatar(raw: bytes) -> tuple[bytes, str]:
    """받은 바이트를 고정 크기 WebP로 다시 그리고 ``(바이트, ETag)``를 돌려준다.

    :raises AvatarTooLargeError: 바이트 상한 초과 (413).
    :raises ValidationError: 디코드 실패 · 받지 않는 형식 (422).

    **ETag를 여기서 함께 낸다.** 바이트와 해시를 다른 곳에서 만들면 둘이 갈릴 수
    있고, 갈리면 화면이 **옛 이미지를 계속 보게 된다** — 서버는 바뀌었는데 ETag가
    그대로라 304를 내기 때문이다. 한 함수가 둘을 함께 낸다.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AvatarTooLargeError()

    try:
        with Image.open(io.BytesIO(raw)) as source:
            fmt = (source.format or "").upper()
            if fmt not in ACCEPTED_FORMATS:
                raise ValidationError(UNREADABLE_MESSAGE, field="file")

            width, height = source.size
            if width * height > MAX_PIXELS:
                raise AvatarTooLargeError(TOO_MANY_PIXELS_MESSAGE)

            # 회전 정보를 **그림에 적용한 뒤** 버린다. 그냥 버리면 세로로 찍은
            # 사진이 눕는다.
            upright = ImageOps.exif_transpose(source) or source
            # 가운데를 정사각으로 잘라 맞춘다 — 눌러서 맞추면 얼굴이 일그러진다.
            square = ImageOps.fit(
                upright.convert("RGBA"),
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
            )
    except AvatarTooLargeError:
        raise
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        # 깨진 파일 · SVG · 형식을 속인 파일이 전부 여기로 온다. 사용자에게는
        # **무엇을 올려야 하는지**만 말한다 — 어디가 깨졌는지는 알 수도 없고
        # 알려 줘도 고칠 수 없다.
        raise ValidationError(UNREADABLE_MESSAGE, field="file") from exc

    out = io.BytesIO()
    # `exif`를 넘기지 않는다 — 넘기지 않는 것이 곧 지우는 것이다.
    square.save(out, format="WEBP", quality=82, method=6)
    rendered = out.getvalue()
    return rendered, hashlib.sha256(rendered).hexdigest()


async def render_avatar_async(raw: bytes) -> tuple[bytes, str]:
    """:func:`render_avatar`를 스레드에서 실행한다 (#2107).

    라우트는 이것을 부른다. 동기 함수를 ``async`` 라우트에서 그대로 부르면 그리는 동안
    **이벤트 루프가 멈춰** 다른 요청(헬스 체크 포함)이 전부 기다린다.

    바이트 상한은 **여기서 먼저** 본다 — 크기만으로 거를 입력에 스레드 확보 비용까지
    치를 이유가 없다(``hash_password_async``의 정책 검사와 같은 판단).
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AvatarTooLargeError()
    return await anyio.to_thread.run_sync(render_avatar, raw, limiter=_render_limiter)
