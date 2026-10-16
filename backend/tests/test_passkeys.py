"""Passkeys, against a software authenticator that signs what a real one would."""

import hashlib
import json
import secrets
from typing import Any

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hashes import SHA256
from httpx import AsyncClient
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers import bytes_to_base64url as b64

from robin import auth, db
from tests.conftest import PASSWORD

ORIGIN = "http://robin.test"


@pytest.fixture(autouse=True)
def fresh_throttle() -> None:
    auth._failures.clear()


class Authenticator:
    """A platform authenticator holding one discoverable P-256 credential."""

    def __init__(self, rp_id: str = "robin.test") -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.rp_id = rp_id
        self.count = 0

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _client_data(self, kind: str, options: dict[str, Any], origin: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": options["challenge"], "origin": origin}
        ).encode()

    def create(self, options: dict[str, Any], origin: str = ORIGIN) -> dict[str, Any]:
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32), -3: numbers.y.to_bytes(32)}
        )
        # User present, user verified, attested credential data included.
        auth_data = (
            self._rp_hash()
            + bytes([0x45])
            + self.count.to_bytes(4)
            + bytes(16)
            + len(self.credential_id).to_bytes(2)
            + self.credential_id
            + cose
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options, origin)),
                "attestationObject": b64(attestation),
                "transports": ["internal", "not-a-transport"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict[str, Any], origin: str = ORIGIN) -> dict[str, Any]:
        self.count += 1
        client_data = self._client_data("webauthn.get", options, origin)
        auth_data = self._rp_hash() + bytes([0x05]) + self.count.to_bytes(4)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(SHA256())
        )
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": b64(b"robin"),
            },
            "clientExtensionResults": {},
        }


async def register(client: AsyncClient, key: Authenticator, origin: str = ORIGIN) -> Any:
    headers = {"origin": origin}
    options = (
        await client.post(
            "/api/auth/passkeys/register/options", headers=headers, json={"password": PASSWORD}
        )
    ).json()
    return await client.post(
        "/api/auth/passkeys/register",
        json={"credential": key.create(options, origin), "label": "Laptop"},
        headers=headers,
    )


async def sign_in(anon: AsyncClient, key: Authenticator, origin: str = ORIGIN) -> Any:
    headers = {"origin": origin}
    options = (await anon.post("/api/auth/passkeys/login/options", headers=headers)).json()
    return await anon.post(
        "/api/auth/passkeys/login", json={"credential": key.get(options, origin)}, headers=headers
    )


async def test_a_passkey_is_registered_and_signs_in(client: AsyncClient, anon: AsyncClient) -> None:
    key = Authenticator()
    resp = await register(client, key)
    assert resp.status_code == 201
    assert resp.json()["label"] == "Laptop"
    stored = db.get_passkey(b64(key.credential_id))
    assert stored is not None
    assert stored["rp_id"] == "robin.test"
    assert json.loads(stored["transports"]) == ["internal"]

    assert (await anon.get("/api/auth/me")).json()["passkeys"] is True
    assert (await sign_in(anon, key)).status_code == 204
    assert (await anon.get("/api/monitored")).status_code == 200
    stored = db.get_passkey(b64(key.credential_id))
    assert stored is not None
    assert stored["sign_count"] == 1
    assert stored["last_used_at"] is not None


async def test_a_passkey_skips_two_factor(client: AsyncClient, anon: AsyncClient) -> None:
    key = Authenticator()
    await register(client, key)
    db.update_account(totp_secret=auth.new_totp_secret())
    assert (await sign_in(anon, key)).status_code == 204


async def test_registering_needs_a_session(anon: AsyncClient) -> None:
    resp = await anon.post(
        "/api/auth/passkeys/register/options", headers={"origin": ORIGIN}, json={"password": "x"}
    )
    assert resp.status_code == 401


async def test_a_challenge_answers_once(client: AsyncClient, anon: AsyncClient) -> None:
    key = Authenticator()
    await register(client, key)
    headers = {"origin": ORIGIN}
    options = (await anon.post("/api/auth/passkeys/login/options", headers=headers)).json()
    first = key.get(options)
    assert (
        await anon.post("/api/auth/passkeys/login", json={"credential": first}, headers=headers)
    ).status_code == 204
    again = await anon.post("/api/auth/passkeys/login", json={"credential": first}, headers=headers)
    assert again.status_code == 400


async def test_a_sign_count_that_goes_back_is_refused(
    client: AsyncClient, anon: AsyncClient
) -> None:
    """A cloned authenticator shows itself by counting from where the original left off."""
    key = Authenticator()
    await register(client, key)
    assert (await sign_in(anon, key)).status_code == 204
    assert (await sign_in(anon, key)).status_code == 204
    key.count = 0
    assert (await sign_in(anon, key)).status_code == 401


async def test_a_passkey_only_signs_in_on_its_own_host(
    client: AsyncClient, anon: AsyncClient
) -> None:
    key = Authenticator()
    await register(client, key)
    elsewhere = Authenticator(rp_id="evil.test")
    elsewhere.key, elsewhere.credential_id = key.key, key.credential_id
    assert (await sign_in(anon, elsewhere, origin="http://evil.test")).status_code == 401


async def test_a_signature_from_another_key_is_refused(
    client: AsyncClient, anon: AsyncClient
) -> None:
    key = Authenticator()
    await register(client, key)
    forged = Authenticator()
    forged.credential_id = key.credential_id
    assert (await sign_in(anon, forged)).status_code == 401


async def test_a_request_without_an_origin_is_refused(anon: AsyncClient) -> None:
    assert (await anon.post("/api/auth/passkeys/login/options")).status_code == 400


async def test_a_passkey_can_be_removed(client: AsyncClient, anon: AsyncClient) -> None:
    key = Authenticator()
    await register(client, key)
    credential_id = b64(key.credential_id)
    assert (await client.delete(f"/api/auth/passkeys/{credential_id}")).status_code == 204
    assert (await client.get("/api/auth/passkeys")).json() == []
    assert (await sign_in(anon, key)).status_code == 401


async def test_reset_forgets_every_passkey(client: AsyncClient) -> None:
    await register(client, Authenticator())
    auth.reset()
    assert db.list_passkeys() == []


async def test_a_passkey_without_user_verification_is_refused(
    client: AsyncClient, anon: AsyncClient
) -> None:
    """A passkey stands in for password and code, so its authenticator must check its holder."""
    key = Authenticator()
    assert (await register(client, key)).status_code == 201

    options = (
        await anon.post("/api/auth/passkeys/login/options", headers={"origin": ORIGIN})
    ).json()
    assert options["userVerification"] == "required"
    assertion = key.get(options)
    # User present only, the verified bit cleared, signed over as a real authenticator would.
    client_data = base64url_to_bytes(assertion["response"]["clientDataJSON"])
    auth_data = key._rp_hash() + bytes([0x01]) + key.count.to_bytes(4)
    signature = key.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(SHA256()))
    assertion["response"]["authenticatorData"] = b64(auth_data)
    assertion["response"]["signature"] = b64(signature)
    resp = await anon.post(
        "/api/auth/passkeys/login", json={"credential": assertion}, headers={"origin": ORIGIN}
    )
    assert resp.status_code == 401


async def test_adding_a_passkey_asks_for_the_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/passkeys/register/options",
        headers={"origin": ORIGIN},
        json={"password": "not the password"},
    )
    assert resp.status_code == 403


async def test_a_wildcard_challenge_spends_nothing_else(
    client: AsyncClient, anon: AsyncClient
) -> None:
    """A challenge is taken by its exact key, so a pattern in it cannot reach other rows."""
    key = Authenticator()
    await register(client, key)
    options = (
        await anon.post("/api/auth/passkeys/login/options", headers={"origin": ORIGIN})
    ).json()

    forged = key.get({"challenge": "%"})
    resp = await anon.post(
        "/api/auth/passkeys/login", json={"credential": forged}, headers={"origin": ORIGIN}
    )
    assert resp.status_code == 400

    real = await anon.post(
        "/api/auth/passkeys/login",
        json={"credential": key.get(options)},
        headers={"origin": ORIGIN},
    )
    assert real.status_code == 204
