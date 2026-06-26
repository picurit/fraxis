# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Input validation, room-name helpers, and error sanitization.

``clamp_limit``, ``require``, ``validate_fields``, ``validate_order_by`` and the
room-name builders are pure: same input → same output, no Frappe access, no side
effects (well_frappe_coding.md §2, §10.3). The field/order_by allowlist functions
receive the set of permitted columns as a parameter so the caller (the service layer,
inside ``run_frappe``) resolves it from ``frappe.get_meta(...).get_valid_columns()`` —
keeping these validators framework-free and unit-testable.

This module is NOT fully import-free: ``sanitize_error`` references Frappe exception
*classes* for ``isinstance`` checks (hence ``import frappe``). It never calls any Frappe
method nor touches ``frappe.db`` / ``frappe.local`` — it is a pure mapping from
exception type to a safe client-facing string.
"""

from typing import Any, Optional

import frappe

DEFAULT_LIMIT = 20
# Server-side hard cap on doctype:list page size. A client may request fewer but never
# more, closing the uncapped-query DoS that also stalls the event loop (analysis S1-3).
MAX_LIMIT = 100


def clamp_limit(limit: Any, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    """Coerce a client-supplied page size into ``1..maximum`` (default on bad input)."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def require(data: Optional[dict], *names: str) -> None:
    """Raise ``ValueError`` if any named key is missing/empty in ``data``."""
    data = data or {}
    missing = [n for n in names if not data.get(n)]
    if missing:
        raise ValueError(f"{' and '.join(missing)} field(s) are required")


# --- Query allowlisting (analysis §7.3 / S1-3) ---------------------------------
#
# Frappe's query layer only *blacklists* SQL-injection patterns; it does not restrict
# client-supplied ``fields`` / ``order_by`` to real columns. These pure validators add a
# positive allowlist: a column is accepted only if it appears in the set the caller
# resolved from the DocType meta. Anything else raises ``ValueError`` (forwarded to the
# client as a safe message by ``sanitize_error``).

_SORT_DIRECTIONS = ("asc", "desc")


def _column_allowed(column: str, allowed: set) -> bool:
    return column == "*" or column in allowed


def validate_fields(fields, allowed: set):
    """Allowlist requested ``fields`` against permitted columns (pure).

    Accepts ``None`` (caller default), a single column string, or a list/tuple of
    columns. Returns the requested fields unchanged on success; raises ``ValueError``
    if any column is not in ``allowed`` (``"*"`` is permitted).
    """
    if not fields:
        return None
    if isinstance(fields, str):
        requested = [fields]
    elif isinstance(fields, (list, tuple)):
        requested = list(fields)
    else:
        raise ValueError("fields must be a string or a list of column names")
    invalid = [f for f in requested if not (isinstance(f, str) and _column_allowed(f.strip(), allowed))]
    if invalid:
        raise ValueError(f"Disallowed field(s): {', '.join(map(str, invalid))}")
    return requested


def validate_order_by(order_by, allowed: set):
    """Allowlist an ``order_by`` clause against permitted columns (pure).

    Accepts ``None`` or a ``"col [asc|desc]"`` string (optionally comma-separated).
    Returns a normalized ``"col asc"``-style string; raises ``ValueError`` on an unknown
    column, a bad sort direction, or an over-complex clause (functions, sub-queries).
    """
    if not order_by:
        return None
    if not isinstance(order_by, str):
        raise ValueError("order_by must be a string")
    normalized = []
    for clause in order_by.split(","):
        clause = clause.strip()
        if not clause:
            continue
        tokens = clause.split()
        if len(tokens) > 2:
            raise ValueError(f"Invalid order_by clause: {clause!r}")
        column = tokens[0]
        direction = tokens[1].lower() if len(tokens) == 2 else "asc"
        if direction not in _SORT_DIRECTIONS:
            raise ValueError(f"Invalid sort direction: {tokens[1]!r}")
        if column == "*" or column not in allowed:
            raise ValueError(f"Disallowed order_by column: {column!r}")
        normalized.append(f"{column} {direction}")
    return ", ".join(normalized) if normalized else None


# --- Room-name builders (one documented contract, used by handlers and workers) ---

def document_room(doctype: str, name: str) -> str:
    """Per-document room (document:update/delete subscribers)."""
    return f"document:{doctype}:{name}"


def collection_room(doctype: str) -> str:
    """Collection room (doctype:subscribe subscribers, all create/update/delete signals)."""
    return f"doctype:{doctype}"


def method_room(method: str) -> str:
    """Method-level room (method:subscribe subscribers)."""
    return f"method:{method}"


def task_room(method: str, task_id: str) -> str:
    """Per-task room — the single canonical room for an enqueued job's events."""
    return f"method:{method}:{task_id}"


# --- Error sanitization (analysis NEW-1, S2-2) ---

# Exception types whose messages are safe to forward to the client.
_SAFE_ERROR_TYPES = (
    ValueError,
    TypeError,
    KeyError,
    frappe.ValidationError,
    frappe.PermissionError,
    frappe.DoesNotExistError,
    frappe.DuplicateEntryError,
    frappe.LinkValidationError,
    frappe.InvalidAuthorizationHeader,
    frappe.InvalidAuthorizationToken,
)


def sanitize_error(exc: Exception) -> str:
    """Return a client-safe error message string.

    Known, well-typed exceptions (validation, permission, not-found) have their
    original message forwarded.  Everything else is replaced with a generic
    placeholder so that SQL state, file paths, connection strings, and internal
    tracebacks never reach the client (analysis S2-2, NEW-1).
    """
    if isinstance(exc, _SAFE_ERROR_TYPES):
        msg = str(exc)
        return msg if msg else type(exc).__name__
    return f"{type(exc).__name__}: operation failed"
