# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
In-source field projection for the document-event bridge (no external config).

Per the ecosystem constraint, the bridge's behavior is driven from fraxis source code,
not from ``common_site_config.json``. This module is the single seam that decides which
fields ride along on a bridged change fact. A generic doctype falls back to ``[]`` so the
fact carries only ``{doctype, name, action}`` — no field leak. A doctype is added to the
bridge payload by editing the ``_PROJECTION`` list here, reviewed and shipped with the
app (``fraxis_improvements_plan.md`` §A.3).

For ``Dendriva State Signal`` the projection exposes its promoted columns **and**
``payload`` because those fields *are* the public contract the widget consumes
(``client_correlation_id`` + ``content`` live inside ``payload``).
"""

from typing import FrozenSet

_PROJECTION: dict[str, list[str]] = {
    "Dendriva State Signal": [
        "scope",
        "event_type",
        "session",
        "session_name",
        "workflow",
        "sequence",
        "message_count",
        "status",
        "finish_reason",
        "payload",
    ],
}

# Fields whose stored value is a JSON string and should be parsed to a dict/list before
# publishing, so both the relay's filter (``payload.client_correlation_id``) and the
# browser client receive a structured object rather than an opaque string.
_JSON_FIELDS: dict[str, FrozenSet[str]] = {
    "Dendriva State Signal": frozenset({"payload"}),
}


def project_fields(doctype: str) -> list[str]:
    """Allowlisted fields to ship for ``doctype`` (``[]`` → only ``name``/``action``)."""
    return _PROJECTION.get(doctype, [])


def json_fields(doctype: str) -> FrozenSet[str]:
    """Projected fields stored as JSON strings that should be parsed before publishing."""
    return _JSON_FIELDS.get(doctype, frozenset())
