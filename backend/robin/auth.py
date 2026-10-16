"""The one account: password, optional TOTP, sessions, and the guard in front of the API.

Default deny. `guard` refuses every path under /api and /img without a session unless it is
in OPEN, so a new router is protected without anyone remembering to. HTTPS is never required:
the session cookie is marked Secure only when the request itself arrived over HTTPS.

The first password is a one-time one printed at start, which signs in only to set another.
Run `python -m robin.auth reset` to forget the password, two factor and passkeys and print a
new one-time password.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import math
import secrets
import struct
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from robin import db

log = logging.getLogger(__name__)

COOKIE = "robin_session"
SESSION_TTL = timedelta(days=30)
# A session is pushed back to a full SESSION_TTL at most once a day, not on every request, and
# never past SESSION_MAX from when it was made.
EXTEND_AFTER = timedelta(days=1)
SESSION_MAX = timedelta(days=90)

# Larger request bodies are refused before anything reads them. Robin's largest is a settings
# save, a few kilobytes, but for a backup uploaded to restore, which carries its own limit.
MAX_BODY = 1024 * 1024
RESTORE_PATH = "/api/backups/restore"
MAX_RESTORE = 64 * 1024 * 1024

PASSWORD_MIN = 8
PASSWORD_MAX = 1024

# Reachable without a session. Logout of nothing is a no-op, and me reports which screen to show.
OPEN = frozenset(
    {
        "/api/health",
        "/api/auth/me",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/passkeys/login/options",
        "/api/auth/passkeys/login",
    }
)
# All a session signed in with the one-time password reaches, beside OPEN.
ONE_TIME = frozenset({"/api/auth/claim"})
PROTECTED = ("/api/", "/img/")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# A cross site form cannot send a custom header, and Robin answers no CORS preflight, so
# requiring one on every write is the whole of the CSRF defence beside SameSite.
CSRF_HEADER = "x-robin"

# No default-src or script-src. Firefox holds the scripts an extension injects to the page's
# policy, and 1Password's passkey support is one, so restricting scripts hands its prompt to
# the browser's own. React escapes everything Robin renders, which leaves a script policy
# little to add.
CSP = "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"

_hasher = PasswordHasher()


# ---------------------------------------------------------------- passwords


def check_password_rules(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"Use at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise ValueError(f"Use at most {PASSWORD_MAX} characters")


# Each Argon2 hash takes 64 MiB on purpose. Two at a time keeps a burst of sign in attempts from
# taking the host's memory with it.
_hashing = threading.BoundedSemaphore(2)


def hash_password(password: str) -> str:
    with _hashing:
        return _hasher.hash(password)


def one_time_password() -> str:
    """A new one-time password, stored hashed, for the caller to print."""
    password = secrets.token_urlsafe(12)
    db.update_account(password_hash=hash_password(password), one_time=1)
    return password


def first_boot() -> None:
    """Print a one-time password while there is no password of the user's own.

    A fresh install opens setup once it is replaced. One printed before a restart is replaced,
    since only its hash was kept.
    """
    account = db.get_account()
    if account["password_hash"] is None:
        db.update_account(setup_step="")
    elif not account["one_time"]:
        return
    print(f"Robin's one-time password for {account['username']}: {one_time_password()}", flush=True)


def password_matches(password: str) -> bool:
    """Verify against the stored hash, rehashing it when the hasher's parameters have moved."""
    stored = db.get_account()["password_hash"]
    if not stored:
        return False
    try:
        with _hashing:
            _hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    if _hasher.check_needs_rehash(stored):
        db.update_account(password_hash=hash_password(password))
    return True


# ---------------------------------------------------------------- TOTP, RFC 6238

TOTP_STEP = 30
TOTP_DIGITS = 6


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def totp_code(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_step_for(secret: str, code: str, after: int, at: float | None = None) -> int | None:
    """The step `code` is valid for, one step of clock drift either way, or None.

    A step at or before `after` is refused, so a code already used cannot be replayed.
    """
    now = int((time.time() if at is None else at) // TOTP_STEP)
    code = code.strip().replace(" ", "")
    for step in (now - 1, now, now + 1):
        if step > after and hmac.compare_digest(totp_code(secret, step), code):
            return step
    return None


def totp_uri(secret: str, username: str) -> str:
    return f"otpauth://totp/Robin:{quote(username)}?secret={secret}&issuer=Robin"


def totp_qr(uri: str) -> str:
    """A data URI for an image, dark on light with a quiet zone, which scans best."""
    # segno leaves the light modules transparent unless told, which on a dark panel puts black
    # on grey and many scanners give up.
    return str(
        segno.make(uri, error="m").svg_data_uri(scale=5, border=4, dark="#000", light="#fff")
    )


# ---------------------------------------------------------------- sessions


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _expiry() -> str:
    return (datetime.now(UTC) + SESSION_TTL).isoformat()


def start_session(request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    db.create_session(_digest(token), _expiry())
    _set_cookie(request, response, token)


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        db.delete_session(_digest(token))
    response.delete_cookie(COOKIE, path="/")


def _live(digest: str) -> str | None:
    """When a live session expires, or None. One made more than SESSION_MAX ago is over."""
    return db.session_expiry(digest, born_after=(datetime.now(UTC) - SESSION_MAX).isoformat())


def current_session(request: Request) -> str | None:
    """The stored digest of the request's session, or None when it has none that is live."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    digest = _digest(token)
    return digest if _live(digest) is not None else None


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        # Robin does not terminate TLS, so a proxy says so. Trusting the header is safe here, the
        # only cookie it can change is the sender's own.
        secure="https" in (request.url.scheme, request.headers.get("x-forwarded-proto")),
    )


def _session_ok(request: Request, response_hook: list[Callable[[Response], None]]) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    digest = _digest(token)
    expires = _live(digest)
    if expires is None:
        return False
    if datetime.fromisoformat(expires) < datetime.now(UTC) + SESSION_TTL - EXTEND_AFTER:
        db.extend_session(digest, _expiry())
        response_hook.append(lambda resp: _set_cookie(request, resp, token))
    return True


# ---------------------------------------------------------------- throttle

THROTTLE_FREE = 5
THROTTLE_MAX = 15 * 60

# Clients remembered at most. The oldest are forgotten first.
THROTTLE_CLIENTS = 10_000

# In memory, one process. Restarting forgets it, and more than one worker would
# each keep their own. Move it to the cache table if Robin ever runs several workers.
_failures: dict[str, tuple[int, float]] = {}
# Sign in runs on a thread pool, so an attempt is counted under a lock.
_throttle = threading.Lock()


def _wait(count: int, last: float) -> int:
    if count < THROTTLE_FREE:
        return 0
    wait = min(1 << (count - THROTTLE_FREE), THROTTLE_MAX)
    return max(0, math.ceil(last + wait - time.monotonic()))


def throttled_for(request: Request) -> int:
    """Seconds this client must wait before another login attempt, zero when it may try."""
    with _throttle:
        return _wait(*_failures.get(_client(request), (0, 0.0)))


def attempt(request: Request) -> int:
    """Count an attempt before it is checked, so attempts sent at once are all counted.

    Returns the seconds to wait first, zero when it may go ahead. A success clears the count.
    """
    client = _client(request)
    with _throttle:
        wait = _wait(*_failures.get(client, (0, 0.0)))
        if wait:
            return wait
        count, _ = _failures.pop(client, (0, 0.0))
        _failures[client] = (count + 1, time.monotonic())
        while len(_failures) > THROTTLE_CLIENTS:
            del _failures[next(iter(_failures))]
    return 0


def clear_failures(request: Request) -> None:
    with _throttle:
        _failures.pop(_client(request), None)


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


# ---------------------------------------------------------------- the guard


def _declared_length(request: Request) -> int:
    try:
        return int(request.headers.get("content-length") or 0)
    except ValueError:
        return MAX_RESTORE + 1


async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path
    hooks: list[Callable[[Response], None]] = []

    if path.startswith(PROTECTED):
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing the X-Robin header"}, status_code=403)
        if _declared_length(request) > (MAX_RESTORE if path == RESTORE_PATH else MAX_BODY):
            return JSONResponse({"detail": "That request is too large"}, status_code=413)
        if path not in OPEN:
            if not _session_ok(request, hooks):
                return JSONResponse({"detail": "Sign in first"}, status_code=401)
            if path not in ONE_TIME and db.get_account()["one_time"]:
                return JSONResponse({"detail": "Set a new password first"}, status_code=403)

    response = await call_next(request)
    for hook in hooks:
        hook(response)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if not path.startswith(PROTECTED):
        response.headers["Content-Security-Policy"] = CSP
    return response


# ---------------------------------------------------------------- recovery


def reset() -> str:
    """Forget two factor and every passkey, end every session, and return a new one-time
    password in place of the password."""
    db.init_db()
    db.update_account(totp_secret=None, totp_last_step=0)
    db.delete_passkeys()
    db.delete_sessions()
    return one_time_password()


if __name__ == "__main__":
    if sys.argv[1:] != ["reset"]:
        sys.exit("usage: python -m robin.auth reset")
    password = reset()
    print(f"Robin's one-time password for {db.get_account()['username']}: {password}")
