"""프로필 이미지 경로 셋 (`#2080`) — **DB로 돈다** (`API_SPEC §1.2.5a`).

`test_avatar.py`가 「받은 바이트를 어떻게 다시 그리나」를 잠그고, 이 파일은
**그것이 경로에 닿는가**를 잠근다. 둘은 따로다 — 서비스가 완벽해도 라우트가
부르지 않으면 아무 일도 일어나지 않고, 그 상태에서도 단위 검사는 전부 초록이다.

## detached 객체 함정 (#279 · #506)

미들웨어는 자기 세션으로 사용자를 조회한 뒤 그 세션을 닫는다. 그 객체를 고치고
라우트 세션으로 commit하면 **아무것도 쓰이지 않는데 204가 나간다.** 그래서 이
파일은 응답이 아니라 **DB를 다시 읽어** 확인한다.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.services.avatar import AVATAR_SIZE, MAX_UPLOAD_BYTES

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"
_URL = "/api/v1/auth/me/avatar"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


def _png(size: tuple[int, int] = (300, 200), color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def _upload(client: TestClient, raw: bytes, *, name: str = "me.png", mime: str = "image/png"):
    return client.post(
        _URL,
        files={"file": (name, raw, mime)},
        headers={"X-CSRF-Token": client.cookies["csrf"]},
    )


def _signup(client: TestClient, email: str) -> None:
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text


async def _stored(email: str) -> dict | None:
    """DB를 직접 읽는다 — 응답만 보면 detached 함정을 못 잡는다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = (
            await s.execute(
                text("SELECT avatar_image, avatar_etag FROM app_user WHERE email = :e"),
                {"e": email},
            )
        ).first()
    return None if row is None else dict(row._mapping)


async def _cleanup(emails: list[str]) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for email in emails:
            await s.execute(
                text(
                    "DELETE FROM user_session WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
            await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


class TestUpload:
    async def test_the_stored_bytes_are_ours_not_the_uploaded_ones(self, client):
        """저장되는 것은 **우리가 다시 그린 바이트**다 (`#2080`).

        원본을 그대로 넣으면 EXIF도 폭탄도 함께 들어온다. 서비스가 아무리
        옳아도 라우트가 결과를 쓰지 않으면 그 모든 것이 무의미하다.
        """
        email = "avatar-upload@example.com"
        try:
            _signup(client, email)
            raw = _png()
            assert _upload(client, raw).status_code == 204

            row = await _stored(email)
            assert row["avatar_image"] is not None, (
                "DB가 비어 있다 — detached 객체를 고치고 commit하면 이렇게 된다 (#279)"
            )
            import base64

            stored = base64.b64decode(row["avatar_image"])
            assert stored != raw, "원본이 그대로 저장됐다 — 다시 그리지 않았다"
            with Image.open(io.BytesIO(stored)) as out:
                assert out.format == "WEBP"
                assert out.size == (AVATAR_SIZE, AVATAR_SIZE)
        finally:
            await _cleanup([email])

    async def test_the_two_columns_are_filled_together(self, client):
        """`avatar_image`와 `avatar_etag`는 **항상 함께** 채워진다.

        한쪽만 차면 `GET`이 ETag는 있는데 본문이 없는 상태로 들어간다 —
        그 상태에서도 업로드 응답은 204다.
        """
        email = "avatar-pair@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())
            row = await _stored(email)
            assert row["avatar_image"] is not None and row["avatar_etag"] is not None
            assert len(row["avatar_etag"]) == 64
        finally:
            await _cleanup([email])

    async def test_a_lying_content_type_changes_nothing(self, client):
        """**확장자와 `Content-Type`을 믿지 않는다.**

        PNG 바이트를 `image/svg+xml`·`.svg`로 보내도 받는다 — 바이트가 형식을
        말하기 때문이다. 반대로 진짜 SVG는 이름을 어떻게 붙여도 막힌다.
        """
        email = "avatar-lie@example.com"
        try:
            _signup(client, email)
            ok = _upload(client, _png(), name="evil.svg", mime="image/svg+xml")
            assert ok.status_code == 204, ok.text

            svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
            bad = _upload(client, svg, name="nice.png", mime="image/png")
            assert bad.status_code == 422, bad.text
        finally:
            await _cleanup([email])

    async def test_oversize_is_413_not_422(self, client):
        """상한 초과와 형식 오류를 **가른다** (`API_SPEC §1.2.5a`).

        고칠 방법이 다르다 — 큰 것은 같은 사진을 줄이면 되고, 형식은 다른 파일을
        골라야 한다. 화면이 그 둘에 다른 말을 하려면 status가 달라야 한다.
        """
        email = "avatar-big@example.com"
        try:
            _signup(client, email)
            resp = _upload(client, b"\x00" * (MAX_UPLOAD_BYTES + 1))
            assert resp.status_code == 413, resp.text
        finally:
            await _cleanup([email])

    async def test_csrf_is_required(self, client):
        email = "avatar-csrf@example.com"
        try:
            _signup(client, email)
            resp = client.post(_URL, files={"file": ("me.png", _png(), "image/png")})
            assert resp.status_code == 403, resp.text
        finally:
            await _cleanup([email])

    async def test_anonymous_cannot_upload(self, client):
        client.cookies.clear()
        resp = client.post(_URL, files={"file": ("me.png", _png(), "image/png")})
        assert resp.status_code in (401, 403), resp.text


class TestFetch:
    async def test_returns_webp_and_an_etag(self, client):
        email = "avatar-get@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())

            resp = client.get(_URL)
            assert resp.status_code == 200, resp.text
            assert resp.headers["content-type"] == "image/webp"
            assert resp.headers["etag"].startswith('"')
            assert "private" in resp.headers["cache-control"]
        finally:
            await _cleanup([email])

    async def test_a_matching_etag_ends_without_a_body(self, client):
        """**사이드바가 매 화면이다.**

        조건부 요청이 안 맞으면 화면 전환마다 수십 KB가 DB에서 나간다 — 그리고
        **그것은 오류로 보이지 않아** 아무도 눈치채지 못한다.
        """
        email = "avatar-304@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())
            etag = client.get(_URL).headers["etag"]

            again = client.get(_URL, headers={"If-None-Match": etag})
            assert again.status_code == 304, again.text
            assert not again.content

            weak = client.get(_URL, headers={"If-None-Match": f"W/{etag}"})
            assert weak.status_code == 304, "W/ 접두를 붙인 재검증이 안 맞는다"

            many = client.get(_URL, headers={"If-None-Match": f'"other", {etag}'})
            assert many.status_code == 304, "여러 개를 보냈을 때 안 맞는다"
        finally:
            await _cleanup([email])

    async def test_a_stale_etag_gets_the_new_bytes(self, client):
        """바꾼 뒤에는 **새 바이트가 나가야** 한다 — 안 그러면 옛 이미지가 남는다."""
        email = "avatar-stale@example.com"
        try:
            _signup(client, email)
            _upload(client, _png(color="red"))
            old = client.get(_URL).headers["etag"]

            _upload(client, _png(color="green"))
            resp = client.get(_URL, headers={"If-None-Match": old})
            assert resp.status_code == 200, "옛 ETag로 304가 나왔다 — 화면이 옛 그림을 계속 본다"
            assert resp.headers["etag"] != old
        finally:
            await _cleanup([email])

    async def test_no_image_is_404(self, client):
        email = "avatar-none@example.com"
        try:
            _signup(client, email)
            assert client.get(_URL).status_code == 404
        finally:
            await _cleanup([email])


class TestDelete:
    async def test_delete_clears_both_columns_and_is_idempotent(self, client):
        """두 번 눌러도 204다.

        두 번째가 404로 떨어지면 사용자는 **지워지지 않은 것으로 읽는다.**
        결과는 같다 — 이미지가 없다.
        """
        email = "avatar-del@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())
            headers = {"X-CSRF-Token": client.cookies["csrf"]}

            assert client.delete(_URL, headers=headers).status_code == 204
            row = await _stored(email)
            assert row["avatar_image"] is None and row["avatar_etag"] is None

            assert client.delete(_URL, headers=headers).status_code == 204
        finally:
            await _cleanup([email])


class TestAccountDelete:
    async def test_withdrawal_leaves_no_image_behind(self, client):
        """탈퇴하면 **사진은 남지 않는다** (`PRD §5.1 [#2080]` ⑷).

        계정 행은 소프트 삭제로 남는다 — 계산·감사 기록의 주체를 되짚어야 하기
        때문이다. 사진은 그 근거가 아니다. 플래그만 세우고 두면 **「지웠다」가
        거짓**이 된다 — `#1330`이 대화 원문에서 겪은 것과 같은 자리다.
        """
        email = "avatar-withdraw@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())

            resp = client.delete(
                "/api/v1/auth/me", headers={"X-CSRF-Token": client.cookies["csrf"]}
            )
            assert resp.status_code == 204, resp.text

            row = await _stored(email)
            assert row is not None, "행까지 지웠다 — 계산·감사 기록의 주체를 잃는다"
            assert row["avatar_image"] is None, "탈퇴했는데 사진이 남아 있다"
            assert row["avatar_etag"] is None
        finally:
            await _cleanup([email])

    async def test_the_audit_event_records_that_it_was_purged(self, client):
        """지운 행은 되짚을 수 없으므로 **지웠다는 사실이 유일한 기록**이다.

        새 감사 경로를 만들지 않고 기존 `ACCOUNT_DELETE`에 얹는다 — 올리기·지우기는
        자기 계정 데이터라 감사 대상이 아니다(`TECH_SPEC §13.1`).
        """
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.db.types import JSONText

        email = "avatar-audit@example.com"
        try:
            _signup(client, email)
            _upload(client, _png())
            client.delete("/api/v1/auth/me", headers={"X-CSRF-Token": client.cookies["csrf"]})

            async with get_sessionmaker()() as s:
                # `action`·`timestamp`는 CUBRID 예약어라 따옴표가 필요하고, raw SQL에는
                # 컬럼 타입이 붙지 않아 `JSONText`를 명시해야 **문자열이 아니라 dict**가
                # 온다 (`#1058` · `tests/test_audit_actions_db.py`와 같은 모양).
                rows = await s.execute(
                    text(
                        "SELECT details_json FROM audit_log "
                        'WHERE "action" = :a ORDER BY "timestamp" DESC'
                    ).columns(details_json=JSONText()),
                    {"a": "ACCOUNT_DELETE"},
                )
                details = rows.mappings().all()[0]["details_json"]
            assert details.get("purged_avatar") is True
        finally:
            async with get_sessionmaker()() as s:
                await s.execute(text("DELETE FROM audit_log"))
                await s.commit()
            await _cleanup([email])
