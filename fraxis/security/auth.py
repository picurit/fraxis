# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Connection authentication for fraxis Socket.IO clients.

Two token shapes are accepted in the Socket.IO ``auth.token`` payload:

1. A raw Frappe API ``key:secret`` (services, trusted backends).
2. A **signed bearer token** ``fxsig1.<payload>.<sig>`` minted server-side by an issuer
   that holds an API key/secret pair (the ``jambonz_widget`` token endpoint). The token
   embeds the ``api_key`` (an identifier) and an expiry, and is HMAC-signed with the
   user's ``api_secret`` — which is the *signing key only* and never travels in the token.
   This lets a browser authenticate to fraxis with a short-lived, auto-renewable token
   while the Frappe credential itself never reaches client JavaScript
   (well_frappe_coding.md §14.2; jambonz_widget security requirement).

The signed-token codec lives here as the single source of truth: the issuer imports
:func:`make_signed_token` so the wire format can never drift between minting and
verification.

:func:`resolve_token_to_user` performs a database lookup and must run inside a Frappe
context (call it through ``run_frappe``). Pure helpers (token parsing, signing) are split
out so they can be unit-tested without Frappe.
"""

import base64
import hashlib
import hmac
import json
import time

import frappe
from frappe.utils.password import get_decrypted_password

# Version-prefixed so the format can evolve and so a signed token is unambiguously
# distinguishable from a raw ``api_key:api_secret`` token.
SIGNED_TOKEN_PREFIX = "fxsig1."


class AuthError(Exception):
    """Raised when a connection token cannot be authenticated."""


def parse_token(token) -> tuple[str, str]:
    """Split an ``api_key:api_secret`` token. Pure — no Frappe access.

    :raises AuthError: if the token is missing or malformed.
    """
    if not token or not isinstance(token, str):
        raise AuthError("Missing authentication token")
    if ":" not in token:
        raise AuthError("Invalid token format: expected 'api_key:api_secret'")
    api_key, api_secret = token.split(":", 1)
    api_key, api_secret = api_key.strip(), api_secret.strip()
    if not api_key or not api_secret:
        raise AuthError("Invalid token: empty api_key or api_secret")
    return api_key, api_secret


# --- Signed bearer token codec (pure helpers) ---------------------------------------

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _sign(payload_b64: str, secret: str) -> str:
    """HMAC-SHA256 of the exact base64url payload string, keyed by the user's secret."""
    digest = hmac.new(str(secret).encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def make_signed_token(api_key: str, api_secret: str, ttl_seconds: int) -> str:
    """Mint a signed, expiring fraxis token. Pure — no Frappe access.

    Called server-side by the issuer (it holds ``api_key``/``api_secret``). Only the
    returned token is ever exposed to the browser; ``api_secret`` is the signing key and
    is not present in the token.
    """
    if not api_key or not api_secret:
        raise AuthError("Cannot mint token without api_key/api_secret")
    now = int(time.time())
    payload = {"k": api_key, "iat": now, "exp": now + int(ttl_seconds)}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{SIGNED_TOKEN_PREFIX}{payload_b64}.{_sign(payload_b64, api_secret)}"


def _resolve_signed_token(token: str) -> str:
    """Verify a ``fxsig1.<payload>.<sig>`` token and return its enabled user.

    Runs inside a Frappe context. The signature is verified with the user's stored
    ``api_secret`` (constant-time), then expiry and enabled-state are checked.
    """
    body = token[len(SIGNED_TOKEN_PREFIX):]
    parts = body.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise AuthError("Invalid token format")
    payload_b64, sig = parts
    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise AuthError("Invalid token payload")

    api_key = claims.get("k")
    exp = claims.get("exp")
    if not api_key or exp is None:
        raise AuthError("Invalid token claims")

    user = frappe.db.get_value("User", {"api_key": api_key}, "name")
    if not user:
        raise AuthError("Invalid credentials")

    stored_secret = get_decrypted_password("User", user, "api_secret", raise_exception=False)
    if not stored_secret or not hmac.compare_digest(sig, _sign(payload_b64, stored_secret)):
        raise AuthError("Invalid credentials")

    try:
        expired = float(exp) < time.time()
    except (TypeError, ValueError):
        raise AuthError("Invalid token claims")
    if expired:
        raise AuthError("Token expired")

    if not frappe.db.get_value("User", user, "enabled"):
        raise AuthError("User is disabled")

    return user


def resolve_token_to_user(token) -> str:
    """Resolve a connection token to an enabled Frappe user.

    Accepts either a signed bearer token (``fxsig1.…``) or a raw ``api_key:api_secret``.
    Runs inside a Frappe context. Uses constant-time secret comparison and verifies the
    user is enabled. :raises AuthError: on any failure (never leaks which check failed).
    """
    if isinstance(token, str) and token.startswith(SIGNED_TOKEN_PREFIX):
        return _resolve_signed_token(token)

    api_key, api_secret = parse_token(token)

    user = frappe.db.get_value("User", {"api_key": api_key}, "name")
    if not user:
        raise AuthError("Invalid credentials")

    stored_secret = get_decrypted_password("User", user, "api_secret", raise_exception=False)
    if not stored_secret or not hmac.compare_digest(str(api_secret), str(stored_secret)):
        raise AuthError("Invalid credentials")

    if not frappe.db.get_value("User", user, "enabled"):
        raise AuthError("User is disabled")

    return user
