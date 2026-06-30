# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Pure, framework-free filter for per-subscriber narrowing of bridged document events.

A client may subscribe to a doctype's change events but only want the documents whose
JSON ``payload`` matches a dynamic condition — e.g. the ``jambonz_widget`` receiving only
the ``Dendriva State Signal`` rows of *its own* in-flight call, matched on
``payload.client_correlation_id``. The matcher is intentionally tiny and total: no
``eval``, no SQL, no arbitrary code; it never raises on malformed data.

Security: a filter only *narrows* delivery within a room the user already passed read
permission for (see ``emit_to_permitted``); it can never widen access
(``fraxis_improvements_plan.md`` §A.2.1).
"""

import json
from typing import Any, Optional

_ALLOWED_OPS = {"eq", "like"}


def normalize_filter(spec: Any) -> Optional[list[dict]]:
    """Validate a client-supplied filter spec into a list of clauses (or ``None``).

    Accepts a single clause ``{"field": "payload.client_correlation_id", "op": "eq",
    "value": "<id>"}`` or a list of such clauses (implicit AND). ``field`` may dot-index
    into the parsed JSON of a top-level field (e.g. the State Signal ``payload``).

    :raises ValueError: on a malformed clause (bad ``field`` type or unknown ``op``).
    """
    if not spec:
        return None
    clauses = spec if isinstance(spec, list) else [spec]
    out: list[dict] = []
    for clause in clauses:
        if not isinstance(clause, dict):
            raise ValueError("invalid filter clause")
        field = clause.get("field")
        op = clause.get("op") or "eq"
        value = clause.get("value")
        if not isinstance(field, str) or not field or op not in _ALLOWED_OPS:
            raise ValueError("invalid filter clause")
        out.append({"field": field, "op": op, "value": value})
    return out or None


def _resolve(data: Any, dotted: str) -> Any:
    """Resolve ``a.b.c`` against ``data``, decoding any JSON string met en route.

    So ``payload.client_correlation_id`` works whether ``payload`` arrives as a dict or
    as a JSON-encoded string. Returns ``None`` if the path cannot be resolved.
    """
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except (ValueError, TypeError):
                return None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def matches(clauses: Optional[list[dict]], data: Optional[dict]) -> bool:
    """True if every clause matches ``data`` (AND). No clauses → always True (unfiltered)."""
    if not clauses:
        return True
    if not isinstance(data, dict):
        return False
    for clause in clauses:
        actual = _resolve(data, clause["field"])
        value = clause["value"]
        op = clause["op"]
        if op == "eq":
            if actual != value:
                return False
        elif op == "like":
            if actual is None or str(value).strip("%") not in str(actual):
                return False
    return True
