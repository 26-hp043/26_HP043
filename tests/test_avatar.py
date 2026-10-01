"""프로필 이미지 — 받은 바이트를 다시 그린다 (`#2080`). **DB 없이 돈다.**

`services/avatar.py`가 하는 일 하나하나가 **무엇을 막으려고 있는지**를 잠근다.
재인코딩은 눈에 보이는 기능이 아니라서, 어느 한 줄이 사라져도 화면은 멀쩡하다 —
EXIF가 남은 것도, 폭탄이 통과한 것도, 형식을 속인 파일이 저장된 것도 **화면에서는
똑같이 「사진이 올라갔다」로 보인다.**
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from cii_platform.errors import ValidationError
from cii_platform.services.avatar import (
    ACCEPTED_FORMATS,
    AVATAR_MEDIA_TYPE,
    AVATAR_SIZE,
    MAX_PIXELS,
    MAX_UPLOAD_BYTES,
    AvatarTooLargeError,
    render_avatar,
)


def _png(size: tuple[int, int] = (300, 200), color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


#: EXIF 태그 번호 — Pillow는 상수 이름을 주지 않는다.
_ORIENTATION = 0x0112
_GPS_IFD = 0x8825
_GPS_LATITUDE_REF = 0x0001
_GPS_LATITUDE = 0x0002


def _jpeg_with_gps(size: tuple[int, int] = (300, 200)) -> bytes:
    """GPS가 든 JPEG — 휴대폰 사진이 실제로 이렇게 생겼다."""
    exif = Image.Exif()
    gps = exif.get_ifd(_GPS_IFD)
    gps[_GPS_LATITUDE_REF] = "N"
    gps[_GPS_LATITUDE] = (37.0, 33.0, 0.0)
    out = io.BytesIO()
    Image.new("RGB", size, "blue").save(out, format="JPEG", exif=exif)
    return out.getvalue()


class TestWhatReEncodingCloses:
    def test_gps_in_the_photo_does_not_reach_storage(self):
        """⚠️ **휴대폰 사진에는 촬영 위치가 들어 있다** (`#2080` ⑴).

        검사만 하고 원본을 저장하면 그 좌표가 DB에 남고, 내보내는 경로로 그대로
        나간다. 이 검사는 **들어올 때는 있었다**는 것까지 함께 주장한다 — 없는
        것을 없다고 해 봐야 아무것도 막지 못한다.
        """
        raw = _jpeg_with_gps()
        with Image.open(io.BytesIO(raw)) as sample:
            assert sample.getexif().get_ifd(_GPS_IFD), (
                "표본에 GPS가 없다 — 검사가 아무것도 막지 못한다"
            )

        rendered, _etag = render_avatar(raw)

        with Image.open(io.BytesIO(rendered)) as out:
            assert not out.info.get("exif"), "EXIF가 그대로 실려 나갔다"
            assert not out.getexif().get_ifd(_GPS_IFD), "GPS가 그대로 실려 나갔다"

    def test_a_small_file_that_unfolds_huge_is_refused(self):
        """압축 폭탄은 **바이트 상한으로 막히지 않는다** (`#2080` ⑵).

        작은 파일이 거대한 픽셀로 펴지는 종류다. 막는 것은 디코드 쪽 상한이다.
        """
        side = int(MAX_PIXELS**0.5) + 100
        raw = _png((side, side), color="black")
        assert len(raw) < MAX_UPLOAD_BYTES, "표본이 바이트 상한에 먼저 걸린다 — 폭탄을 못 잰다"

        with pytest.raises(AvatarTooLargeError):
            render_avatar(raw)

    def test_the_bytes_decide_the_format_not_the_name(self):
        """확장자도 `Content-Type`도 보지 않는다 (`#2080` ⑶).

        이 함수는 **파일 이름을 받지 않는다** — 그것이 곧 「믿지 않는다」의 구현이다.
        속일 수 있는 입력이 애초에 들어오지 않는다.
        """
        assert "filename" not in render_avatar.__code__.co_varnames
        assert "content_type" not in render_avatar.__code__.co_varnames

    def test_output_size_does_not_follow_input_size(self):
        """저장 크기가 고정된다 (`#2080` ⑷).

        `Base64Bytes`가 바이트를 4/3로 불리므로(`DB_SCHEMA §2.15`), 들어오는 쪽이
        열려 있으면 그 4/3도 열린 값이 된다.
        """
        small, _ = render_avatar(_png((64, 64)))
        large, _ = render_avatar(_png((1600, 1200)))

        for rendered in (small, large):
            with Image.open(io.BytesIO(rendered)) as out:
                assert out.size == (AVATAR_SIZE, AVATAR_SIZE)
                assert out.format == "WEBP"


class TestWhatIsRefused:
    def test_svg_is_refused(self):
        """SVG는 **스크립트를 품을 수 있다.**

        우리가 그것을 내보내면 같은 출처에서 남의 스크립트가 도는 길이 된다.
        """
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(ValidationError):
            render_avatar(svg)

    def test_the_accepted_set_is_closed(self):
        """허용 형식이 **닫힌 집합**이다.

        지금은 Pillow가 SVG를 열지 못해 위 검사가 통과하지만, 그것은 **우연**이다.
        Pillow가 언젠가 SVG를 열게 되어도 이 집합이 막는다.
        """
        assert frozenset({"PNG", "JPEG", "WEBP"}) == ACCEPTED_FORMATS
        assert "SVG" not in ACCEPTED_FORMATS

    def test_a_gif_is_refused_even_though_pillow_reads_it(self):
        """Pillow가 **읽을 수 있는데도** 거절한다 — 집합이 일을 한다는 증거다."""
        out = io.BytesIO()
        Image.new("P", (10, 10)).save(out, format="GIF")
        with pytest.raises(ValidationError):
            render_avatar(out.getvalue())

    def test_broken_bytes_are_refused(self):
        with pytest.raises(ValidationError):
            render_avatar(b"not an image at all")

    def test_oversize_is_refused_before_decoding(self):
        """상한 초과는 **디코더에 들어가기 전에** 걸린다.

        거대한 파일을 디코더에 넘긴 뒤 판정하면, 판정하기 전에 메모리를 먼저 쓴다.
        """
        with pytest.raises(AvatarTooLargeError):
            render_avatar(b"\x00" * (MAX_UPLOAD_BYTES + 1))


class TestEtag:
    def test_etag_comes_from_the_rendered_bytes(self):
        """ETag는 **내보낼 바이트**에서 나온다 — 받은 바이트가 아니다.

        받은 쪽에서 내면, 다른 원본이 같은 결과로 그려졌을 때 ETag만 달라져
        **같은 그림을 다시 받는다.** 반대로 재인코딩이 바뀌어 결과가 달라졌는데
        ETag가 그대로면 화면이 **옛 이미지를 계속 본다.**
        """
        import hashlib

        rendered, etag = render_avatar(_png())
        assert etag == hashlib.sha256(rendered).hexdigest()

    def test_same_input_same_etag_different_input_different_etag(self):
        a1, e1 = render_avatar(_png(color="red"))
        a2, e2 = render_avatar(_png(color="red"))
        _b, e3 = render_avatar(_png(color="green"))

        assert a1 == a2 and e1 == e2
        assert e1 != e3

    def test_etag_fits_the_column(self):
        """`DB_SCHEMA §2.15`의 `avatar_etag`가 VARCHAR(64)다 — 넘치면 잘려 저장된다."""
        _rendered, etag = render_avatar(_png())
        assert len(etag) == 64


class TestOrientation:
    def test_a_rotated_photo_is_not_stored_the_same_as_an_unrotated_one(self):
        """회전 정보를 **그림에 적용한 뒤** 버린다.

        그냥 버리면 세로로 찍은 사진이 눕는다 — EXIF를 지우는 일이 흔히 같이
        데려오는 결함이고, **결과 그림만 보면 멀쩡해 보인다.**

        값을 주장하지 않고 **관계**를 잠근다 — 회전 정보를 무시했다면 EXIF가 없는
        같은 그림과 결과가 **한 바이트도 다르지 않을** 것이다.
        """
        source = Image.new("RGB", (200, 100), "black")
        for x in range(200):
            for y in range(20):
                source.putpixel((x, y), (255, 0, 0))

        plain = io.BytesIO()
        source.save(plain, format="JPEG")

        exif = Image.Exif()
        exif[_ORIENTATION] = 6
        rotated = io.BytesIO()
        source.save(rotated, format="JPEG", exif=exif)

        upright, _ = render_avatar(rotated.getvalue())
        as_is, _ = render_avatar(plain.getvalue())
        assert upright != as_is, "회전 정보가 그림에 반영되지 않았다"


def test_media_type_is_the_one_format_we_store():
    """저장 형식이 하나이므로 MIME도 하나다 — 열마다 형식을 적지 않는 이유다."""
    assert AVATAR_MEDIA_TYPE == "image/webp"
