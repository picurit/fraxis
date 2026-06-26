# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Connection authentication for fraxis Socket.IO clients.

Clients authenticate with a Frappe API ``key:secret`` token in the Socket.IO ``auth``
payload. The resolved user is bound to the connection and applied per operation via
``frappe.set_user`` so ``frappe.has_permission`` becomes meaningful (analysis §7.1-7.2).

:func:`resolve_token_to_user` performs a database lookup and must run inside a Frappe
context (call it through ``run_frappe``). Token parsing is split into a pure helper so it
can be unit-tested without Frappe.
"""

import hmac

import frappe
from frappe.utils.password import get_decrypted_password


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


def resolve_token_to_user(token) -> str:
    """Resolve an ``api_key:api_secret`` token to an enabled Frappe user.

    Runs inside a Frappe context. Uses a constant-time secret comparison and verifies the
    user is enabled. :raises AuthError: on any failure (never leaks which check failed).
    """
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
