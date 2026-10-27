"""Signing in and out, replacing the one-time password, setup, two factor and passkeys."""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from robin import __version__, auth, db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOTP_PENDING_KEY = "auth:totp:pending"
TOTP_PENDING_TTL = 10 * 60

Password = Field(max_length=auth.PASSWORD_MAX)


class Me(BaseModel):
    """Which screen to show. The username and the version are only told to someone signed in."""

    signed_in: bool
    username: str
    # The password is the one printed at start. Told to anyone, so sign in says where it is.
    one_time: bool
    # The setup step to open at, '' for the first, None once setup is done.
    setup: str | None
    totp: bool
    # Told to anyone, so sign in knows whether to offer a passkey.
    passkeys: bool
    version: str


class ClaimIn(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=64)
    password: str = Password


class SetupIn(BaseModel):
    step: str | None = Field(max_length=32)


# Six digits, spaces allowed between them as authenticator apps show them.
Code = Field(pattern=r"^[0-9 ]{0,12}$", max_length=12)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Password
    code: str = Field(default="", pattern=r"^[0-9 ]{0,12}$", max_length=12)


class LoginOut(BaseModel):
    """`needs_code` means the password was right and the TOTP code is still to come."""

    needs_code: bool


class PasswordIn(BaseModel):
    current: str = Password
    new: str = Password


class TotpSetup(BaseModel):
    secret: str
    uri: str
    qr: str


class CodeIn(BaseModel):
    code: str = Code


class ConfirmIn(BaseModel):
    password: str = Password


def _confirm(password: str) -> None:
    """The current password, asked again before anything that changes how Robin is entered."""
    if not auth.password_matches(password):
        raise HTTPException(status_code=403, detail="The password is wrong")


def _rules(password: str) -> None:
    try:
        auth.check_password_rules(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/me")
def me(request: Request) -> Me:
    account = db.get_account()
    signed_in = auth.current_session(request) is not None
    return Me(
        signed_in=signed_in,
        username=account["username"] if signed_in else "",
        one_time=bool(account["one_time"]),
        setup=account["setup_step"] if signed_in else None,
        totp=signed_in and account["totp_secret"] is not None,
        passkeys=bool(db.list_passkeys()),
        version=__version__ if signed_in else "",
    )


@router.post("/claim", status_code=204)
def claim(body: ClaimIn, request: Request) -> None:
    """Replace the one-time password, ending every other session signed in with it."""
    if not db.get_account()["one_time"]:
        raise HTTPException(status_code=409, detail="Robin already has a password")
    _rules(body.password)
    # Two sessions claiming at once: the first write wins, the other is refused.
    if not db.claim_account(body.username.strip(), auth.hash_password(body.password)):
        raise HTTPException(status_code=409, detail="Robin already has a password")
    db.delete_sessions(keep=auth.current_session(request))
    log.info("account claimed from %s", request.client.host if request.client else "?")


@router.put("/setup", status_code=204)
def setup(body: SetupIn) -> None:
    """Setup moves past its notifications step only once a destination is set."""
    if body.step not in BEFORE_NOTIFICATIONS and not db.get_settings().notify_ready:
        raise HTTPException(status_code=409, detail="Add a notification destination first")
    db.set_setup_step(body.step)


# The setup steps up to and including notifications, open while no destination is set.
BEFORE_NOTIFICATIONS = frozenset({"", "restore", "species", "notifications"})


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> LoginOut:
    wait = auth.attempt(request)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many attempts, wait {wait} seconds")

    account = db.get_account()
    # The hash is checked whatever the username, so a wrong name costs the same as a wrong
    # password and the two cannot be told apart.
    password_ok = auth.password_matches(body.password)
    name_ok = secrets.compare_digest(
        body.username.strip().casefold().encode(), account["username"].casefold().encode()
    )
    if not (password_ok and name_ok):
        log.warning("login failed from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=401, detail="Wrong username or password")

    secret = account["totp_secret"]
    if secret:
        if not body.code:
            return LoginOut(needs_code=True)
        step = auth.totp_step_for(secret, body.code, after=account["totp_last_step"])
        # Spent in the same statement that checks it, so a code sent twice at once counts once.
        if step is None or not db.spend_totp_step(step):
            log.warning(
                "login code refused from %s", request.client.host if request.client else "?"
            )
            raise HTTPException(status_code=401, detail="Wrong code")

    auth.clear_failures(request)
    auth.start_session(request, response)
    log.info("signed in from %s", request.client.host if request.client else "?")
    return LoginOut(needs_code=False)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    auth.end_session(request, response)


@router.post("/sign-out-everywhere", status_code=204)
def sign_out_everywhere(response: Response) -> None:
    db.delete_sessions()
    response.delete_cookie(auth.COOKIE, path="/")
    log.info("every session ended")


@router.post("/password", status_code=204)
def change_password(body: PasswordIn, request: Request) -> None:
    """Every other session ends, the one making the change stays signed in."""
    if not auth.password_matches(body.current):
        raise HTTPException(status_code=403, detail="The current password is wrong")
    _rules(body.new)
    db.update_account(password_hash=auth.hash_password(body.new))
    db.delete_sessions(keep=auth.current_session(request))
    log.info("password changed")


@router.post("/totp/setup")
def totp_setup(body: ConfirmIn) -> TotpSetup:
    """A fresh secret, held aside until a code from it proves the app has it.

    Asks for the password, so a browser left signed in cannot add a factor of its own.
    """
    _confirm(body.password)
    account = db.get_account()
    if account["totp_secret"]:
        raise HTTPException(status_code=409, detail="Two factor is already on")
    secret = auth.new_totp_secret()
    db.cache_put(TOTP_PENDING_KEY, secret, TOTP_PENDING_TTL)
    uri = auth.totp_uri(secret, account["username"])
    return TotpSetup(secret=secret, uri=uri, qr=auth.totp_qr(uri))


@router.post("/totp/enable", status_code=204)
def totp_enable(body: CodeIn) -> None:
    secret = db.cache_get(TOTP_PENDING_KEY)
    if not isinstance(secret, str):
        raise HTTPException(status_code=409, detail="That setup expired, start again")
    step = auth.totp_step_for(secret, body.code, after=0)
    if step is None:
        raise HTTPException(status_code=422, detail="Wrong code")
    db.update_account(totp_secret=secret, totp_last_step=step)
    db.cache_drop(TOTP_PENDING_KEY)
    log.info("two factor turned on")


@router.post("/totp/disable", status_code=204)
def totp_disable(body: ConfirmIn) -> None:
    _confirm(body.password)
    db.update_account(totp_secret=None, totp_last_step=0)
    log.info("two factor turned off")


# ---------------------------------------------------------------- passkeys

CHALLENGE_TTL = 5 * 60
# One account, so one fixed handle. An authenticator keeps one passkey per site and handle,
# and exclude_credentials stops a second one being made on the same authenticator.
USER_HANDLE = b"robin"


class Passkey(BaseModel):
    id: str
    label: str
    created_at: str
    last_used_at: str | None


class PasskeyIn(BaseModel):
    credential: dict[str, Any]
    label: str = Field(default="Passkey", min_length=1, max_length=64)


class AssertionIn(BaseModel):
    credential: dict[str, Any]


def _origin(request: Request) -> tuple[str, str]:
    """The page's origin and the host it names, which is the passkey's relying party.

    Taken from the Origin header the browser sets rather than from Host, which a reverse proxy
    may rewrite. The browser only lets a page use a passkey made for its own host, and each
    passkey keeps the host it was made on, so this cannot reach a passkey of another site.
    """
    origin = request.headers.get("origin", "")
    host = urlsplit(origin).hostname
    if not host:
        raise HTTPException(status_code=400, detail="The request carries no origin")
    return origin, host


def _challenge_key(challenge: str) -> str:
    return f"auth:webauthn:{challenge}"


def _hold(challenge: bytes, kind: str) -> None:
    db.cache_put(_challenge_key(bytes_to_base64url(challenge)), kind, CHALLENGE_TTL)


def _take(credential: dict[str, Any], kind: str) -> bytes:
    """The challenge a credential answers, spent the moment it is read."""
    try:
        client_data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        challenge = str(client_data["challenge"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="That is not a passkey response") from exc
    held = db.cache_take(_challenge_key(challenge))
    if held != kind:
        raise HTTPException(status_code=400, detail="That request expired, try again")
    return base64url_to_bytes(challenge)


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


@router.get("/passkeys")
def list_passkeys() -> list[Passkey]:
    return [Passkey(**row) for row in db.list_passkeys()]


@router.post("/passkeys/register/options")
def register_options(body: ConfirmIn, request: Request) -> Any:
    """Asks for the password, so a browser left signed in cannot add a passkey of its own."""
    _confirm(body.password)
    _, rp_id = _origin(request)
    username = db.get_account()["username"]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Robin",
        user_id=USER_HANDLE,
        user_name=username,
        user_display_name=username,
        # A passkey stands in for the password and the code, so the authenticator has to
        # check who holds it, a PIN or a biometric, every time.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(row["id"]),
                transports=[AuthenticatorTransport(t) for t in json.loads(row["transports"])],
            )
            for row in db.list_passkeys()
            if row["rp_id"] == rp_id
        ],
    )
    _hold(options.challenge, "register")
    return json.loads(options_to_json(options))


@router.post("/passkeys/register", status_code=201)
def register(body: PasskeyIn, request: Request) -> Passkey:
    origin, rp_id = _origin(request)
    challenge = _take(body.credential, "register")
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(status_code=400, detail=f"The passkey was refused: {exc}") from exc

    credential_id = bytes_to_base64url(verified.credential_id)
    known = {t.value for t in AuthenticatorTransport}
    transports = (body.credential.get("response") or {}).get("transports") or []
    if not isinstance(transports, list):
        transports = []
    db.add_passkey(
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        rp_id=rp_id,
        transports=[t for t in transports if isinstance(t, str) and t in known],
        label=body.label.strip(),
    )
    log.info("passkey added for %s", rp_id)
    stored = db.get_passkey(credential_id)
    assert stored is not None
    return Passkey(**stored)


@router.delete("/passkeys/{credential_id}", status_code=204)
def remove_passkey(credential_id: str) -> None:
    if not db.delete_passkeys(credential_id):
        raise HTTPException(status_code=404, detail="No such passkey")
    log.info("passkey removed")


@router.post("/passkeys/login/options")
def login_options(request: Request) -> Any:
    """No allowCredentials: the authenticator offers whichever passkey it holds for the host."""
    _, rp_id = _origin(request)
    if auth.throttled_for(request):
        raise HTTPException(status_code=429, detail="Too many attempts, wait a moment")
    options = generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED
    )
    _hold(options.challenge, "login")
    return json.loads(options_to_json(options))


@router.post("/passkeys/login", status_code=204)
def passkey_login(body: AssertionIn, request: Request, response: Response) -> None:
    """A passkey is its own second factor, so TOTP is not asked for."""
    wait = auth.attempt(request)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many attempts, wait {wait} seconds")
    origin, rp_id = _origin(request)
    challenge = _take(body.credential, "login")
    stored = db.get_passkey(str(body.credential.get("rawId", "")))
    try:
        if stored is None or stored["rp_id"] != rp_id:
            raise InvalidAuthenticationResponse("unknown passkey")
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=stored["public_key"],
            credential_current_sign_count=stored["sign_count"],
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        log.warning("passkey sign in refused from %s: %s", _client(request), exc)
        raise HTTPException(status_code=401, detail="That passkey was not accepted") from exc

    db.passkey_used(stored["id"], verified.new_sign_count)
    auth.clear_failures(request)
    auth.start_session(request, response)
    log.info("signed in with a passkey from %s", _client(request))
