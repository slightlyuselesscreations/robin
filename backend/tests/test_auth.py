"""The one account, its sessions, and the guard in front of everything under /api and /img."""

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import Request
from httpx import AsyncClient

from robin import __version__, auth, db
from robin.main import app
from tests.conftest import PASSWORD, notify_to


@pytest.fixture(autouse=True)
def fresh_throttle() -> None:
    auth._failures.clear()


async def login(
    c: AsyncClient, username: str = "admin", password: str = PASSWORD, code: str = ""
) -> httpx.Response:
    return await c.post(
        "/api/auth/login", json={"username": username, "password": password, "code": code}
    )


# ---------------------------------------------------------------- the guard


async def test_every_route_but_the_open_ones_refuses_without_a_session(anon: AsyncClient) -> None:
    """Default deny: a route added later is covered without anyone listing it."""
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        assert path.startswith(auth.PROTECTED), f"{path} is outside the guard"
        if path in auth.OPEN:
            continue
        url = path.replace("{", "").replace("}", "")
        for method in operations:
            resp = await anon.request(method.upper(), url)
            assert resp.status_code == 401, f"{method} {path} answered {resp.status_code}"
            checked += 1
    assert checked > 20


def test_nothing_but_the_api_and_the_spa_is_routed() -> None:
    """The SPA catch all and its assets are the only routes outside the guard."""
    outside = {
        getattr(route, "path", "")
        for route in app.routes
        if not getattr(route, "path", "/api/").startswith(auth.PROTECTED)
    }
    assert outside <= {"/{path:path}", "/assets"}


async def test_images_need_a_session(anon: AsyncClient) -> None:
    assert (await anon.get("/img/cover_big/abc.jpg")).status_code == 401


async def test_the_shell_cannot_be_framed_and_leaves_scripts_to_extensions(
    anon: AsyncClient,
) -> None:
    """A policy on scripts would block the passkey hook 1Password injects in Firefox."""
    policy = (await anon.get("/settings")).headers["content-security-policy"]
    assert "frame-ancestors 'none'" in policy
    assert "default-src" not in policy and "script-src" not in policy


async def test_health_stays_open(anon: AsyncClient) -> None:
    resp = await anon.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_a_write_without_the_header_is_refused(client: AsyncClient) -> None:
    resp = await client.post("/api/monitored/clear-found", headers={auth.CSRF_HEADER: ""})
    assert resp.status_code == 403
    assert (await client.post("/api/monitored/clear-found")).status_code == 204


async def test_an_expired_session_is_refused(anon: AsyncClient) -> None:
    db.create_session(auth._digest("old"), "2000-01-01T00:00:00+00:00")
    anon.cookies.set(auth.COOKIE, "old")
    assert (await anon.get("/api/monitored")).status_code == 401


async def test_a_session_is_pushed_back_once_a_day_has_passed(anon: AsyncClient) -> None:
    db.create_session(auth._digest("t"), (datetime.now(UTC) + timedelta(days=3)).isoformat())
    anon.cookies.set(auth.COOKIE, "t")
    resp = await anon.get("/api/monitored")
    assert resp.status_code == 200
    assert auth.COOKIE in resp.headers.get("set-cookie", "")
    expires = db.session_expiry(auth._digest("t"))
    assert expires is not None
    assert expires > (datetime.now(UTC) + timedelta(days=29)).isoformat()


# ---------------------------------------------------------------- claiming


def printed_password(capsys: pytest.CaptureFixture[str]) -> str:
    auth.first_boot()
    return capsys.readouterr().out.strip().rsplit(" ", 1)[1]


async def test_the_one_time_password_only_sets_another(
    anon: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    one_time = printed_password(capsys)
    assert (await anon.get("/api/auth/me")).json()["one_time"] is True, "told before sign in"
    assert (await anon.get("/api/auth/me")).json()["version"] == "", "told only once signed in"
    assert (await login(anon, password=one_time)).status_code == 200
    me = (await anon.get("/api/auth/me")).json()
    assert me["one_time"] is True and me["setup"] == ""
    assert (await anon.get("/api/monitored")).status_code == 403

    resp = await anon.post("/api/auth/claim", json={"username": "wise", "password": PASSWORD})
    assert resp.status_code == 204
    assert (await anon.get("/api/auth/me")).json() == {
        "signed_in": True,
        "username": "wise",
        "one_time": False,
        "setup": "",
        "totp": False,
        "passkeys": False,
        "version": __version__,
    }
    assert (await anon.get("/api/monitored")).status_code == 200
    assert not auth.password_matches(one_time)

    again = await anon.post("/api/auth/claim", json={"password": "another password"})
    assert again.status_code == 409


async def test_claiming_ends_every_other_session(
    anon: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    one_time = printed_password(capsys)
    db.create_session(auth._digest("other"), "9999-12-31T00:00:00+00:00")
    await login(anon, password=one_time)
    await anon.post("/api/auth/claim", json={"password": PASSWORD})
    assert db.session_expiry(auth._digest("other")) is None


def test_a_restart_replaces_an_unused_one_time_password(capsys: pytest.CaptureFixture[str]) -> None:
    first = printed_password(capsys)
    db.set_setup_step("games")
    second = printed_password(capsys)
    assert first != second and auth.password_matches(second)
    assert db.get_account()["setup_step"] == "games", "only a fresh install opens setup"


def test_an_install_with_a_password_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    db.update_account(password_hash=auth.hash_password(PASSWORD))
    auth.first_boot()
    assert capsys.readouterr().out == ""
    assert db.get_account()["setup_step"] is None


@pytest.mark.parametrize(
    ("headers", "secure"), [({}, False), ({"X-Forwarded-Proto": "https"}, True)]
)
async def test_the_cookie_is_secure_when_a_proxy_says_https(
    anon: AsyncClient, headers: dict[str, str], secure: bool
) -> None:
    db.update_account(password_hash=auth.hash_password(PASSWORD))
    resp = await anon.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers=headers,
    )
    assert ("Secure" in resp.headers["set-cookie"]) is secure


async def test_a_short_password_is_refused(
    anon: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await login(anon, password=printed_password(capsys))
    resp = await anon.post("/api/auth/claim", json={"password": "short"})
    assert resp.status_code == 422
    assert db.get_account()["one_time"] == 1


async def test_setup_moves_on_and_never_reopens(client: AsyncClient) -> None:
    db.update_account(setup_step="")
    db.save_settings(notify_to())
    assert (await client.put("/api/auth/setup", json={"step": "games"})).status_code == 204
    assert (await client.get("/api/auth/me")).json()["setup"] == "games"
    await client.put("/api/auth/setup", json={"step": None})
    await client.put("/api/auth/setup", json={"step": "games"})
    assert (await client.get("/api/auth/me")).json()["setup"] is None


def test_reset_prints_a_new_one_time_password() -> None:
    db.update_account(password_hash="x", totp_secret="ABC")
    db.create_session("digest", "9999-01-01T00:00:00+00:00")
    password = auth.reset()
    account = db.get_account()
    assert auth.password_matches(password) and account["one_time"] == 1
    assert account["totp_secret"] is None
    assert account["setup_step"] is None
    assert db.session_expiry("digest") is None


# ---------------------------------------------------------------- signing in


async def test_signing_in_and_out(client: AsyncClient, anon: AsyncClient) -> None:
    assert (await login(anon, username="ADMIN")).json() == {"needs_code": False}
    assert (await anon.get("/api/monitored")).status_code == 200
    assert (await anon.post("/api/auth/logout")).status_code == 204
    assert (await anon.get("/api/monitored")).status_code == 401


async def test_a_wrong_name_and_a_wrong_password_read_the_same(
    client: AsyncClient, anon: AsyncClient
) -> None:
    name = await login(anon, username="root")
    password = await login(anon, password="wrong password")
    assert name.status_code == password.status_code == 401
    assert name.json() == password.json()


async def test_repeated_failures_are_slowed_down(client: AsyncClient, anon: AsyncClient) -> None:
    for _ in range(auth.THROTTLE_FREE):
        assert (await login(anon, password="wrong password")).status_code == 401
    assert (await login(anon)).status_code == 429


async def test_an_old_hash_is_upgraded_on_sign_in(client: AsyncClient, anon: AsyncClient) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    db.update_account(password_hash=weak)
    assert (await login(anon)).status_code == 200
    stored = db.get_account()["password_hash"]
    assert stored != weak
    assert not PasswordHasher().check_needs_rehash(stored)


async def test_changing_the_password_ends_every_other_session(
    client: AsyncClient, anon: AsyncClient
) -> None:
    await login(anon)
    resp = await client.post(
        "/api/auth/password", json={"current": PASSWORD, "new": "a brand new password"}
    )
    assert resp.status_code == 204
    assert (await client.get("/api/monitored")).status_code == 200
    assert (await anon.get("/api/monitored")).status_code == 401
    assert (await login(anon, password="a brand new password")).status_code == 200


async def test_sign_out_everywhere(client: AsyncClient) -> None:
    assert (await client.post("/api/auth/sign-out-everywhere")).status_code == 204
    assert (await client.get("/api/monitored")).status_code == 401


# ---------------------------------------------------------------- TOTP


def test_totp_matches_the_rfc_6238_vector() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode()
    # RFC 6238 appendix B, SHA-1 at T = 59, cut to six digits.
    assert auth.totp_code(secret, 59 // 30) == "287082"


def test_a_used_code_cannot_be_used_again() -> None:
    secret = auth.new_totp_secret()
    at = 1_000_000.0
    code = auth.totp_code(secret, int(at // 30))
    step = auth.totp_step_for(secret, code, after=0, at=at)
    assert step == int(at // 30)
    assert auth.totp_step_for(secret, code, after=step, at=at) is None


async def test_two_factor_from_setup_to_sign_in(client: AsyncClient, anon: AsyncClient) -> None:
    refused = await client.post("/api/auth/totp/setup", json={"password": "not it at all"})
    assert refused.status_code == 403, "a signed in browser alone cannot add a factor"
    setup = (await client.post("/api/auth/totp/setup", json={"password": PASSWORD})).json()
    assert setup["qr"].startswith("data:image/svg+xml")
    secret = setup["secret"]
    step = int(datetime.now(UTC).timestamp() // 30)
    resp = await client.post("/api/auth/totp/enable", json={"code": auth.totp_code(secret, step)})
    assert resp.status_code == 204
    assert (await client.get("/api/auth/me")).json()["totp"] is True

    assert (await login(anon)).json() == {"needs_code": True}
    assert (await anon.get("/api/monitored")).status_code == 401
    # The step enable used is spent, so only a later one signs in.
    assert (await login(anon, code=auth.totp_code(secret, step))).status_code == 401
    assert (await login(anon, code=auth.totp_code(secret, step + 1))).status_code == 200
    assert (await anon.get("/api/monitored")).status_code == 200


async def test_turning_two_factor_off_needs_the_password(client: AsyncClient) -> None:
    db.update_account(totp_secret=auth.new_totp_secret())
    wrong = await client.post("/api/auth/totp/disable", json={"password": "nope nope nope"})
    assert wrong.status_code == 403
    right = await client.post("/api/auth/totp/disable", json={"password": PASSWORD})
    assert right.status_code == 204
    assert db.get_account()["totp_secret"] is None


def test_the_qr_code_is_black_on_white_with_its_quiet_zone() -> None:
    svg = unquote(auth.totp_qr(auth.totp_uri(auth.new_totp_secret(), "admin")))
    assert "fill='#fff'" in svg or 'fill="#fff"' in svg
    assert "#000" in svg


async def test_a_second_claim_at_the_same_time_is_refused() -> None:
    auth.one_time_password()
    assert db.claim_account("admin", auth.hash_password("first password"))
    assert not db.claim_account("admin", auth.hash_password("second password"))
    assert auth.password_matches("first password")


def test_a_code_is_spent_once_even_when_sent_twice_at_once() -> None:
    assert db.spend_totp_step(100)
    assert not db.spend_totp_step(100)
    assert not db.spend_totp_step(99)
    assert db.spend_totp_step(101)


async def test_attempts_sent_at_once_are_all_counted(anon: AsyncClient) -> None:
    auth._failures.clear()
    request = Request({"type": "http", "client": ("198.51.100.7", 1), "headers": []})
    for _ in range(auth.THROTTLE_FREE):
        assert auth.attempt(request) == 0
    assert auth.attempt(request) > 0
    auth.clear_failures(request)
    assert auth.attempt(request) == 0


async def test_a_session_ends_after_its_longest_life(anon: AsyncClient) -> None:
    born = (datetime.now(UTC) - auth.SESSION_MAX - timedelta(days=1)).isoformat()
    with db.conn() as c:
        c.execute(
            "INSERT INTO sessions (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (auth._digest("old"), born, "9999-12-31T00:00:00+00:00"),
        )
    anon.cookies.set(auth.COOKIE, "old")
    assert (await anon.get("/api/monitored")).status_code == 401


async def test_an_oversized_body_is_refused_before_it_is_read(anon: AsyncClient) -> None:
    resp = await anon.post(
        "/api/auth/login",
        content=b"{}",
        headers={"content-length": str(auth.MAX_BODY + 1), "content-type": "application/json"},
    )
    assert resp.status_code == 413


async def test_there_is_no_docs_page(client: AsyncClient) -> None:
    assert (await client.get("/api/docs")).status_code == 404
    assert (await client.get("/api/openapi.json")).status_code == 200


async def test_a_local_client_still_signs_in(anon: AsyncClient) -> None:
    """No address is let in without a session."""
    # The in process transport reports 127.0.0.1 as the client.
    assert (await anon.get("/api/monitored")).status_code == 401
    assert (await anon.get("/api/auth/me")).json()["signed_in"] is False
