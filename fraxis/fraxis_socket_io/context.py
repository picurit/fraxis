# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Shared per-request metadata for Socket.IO responses."""

from datetime import datetime, timezone

import frappe


def build_metadata(sid: str) -> dict:
    """Build the standard response metadata (timestamp, sid, site).

    Reads only process-level, read-only state on the loop thread; never raises.
    """
    try:
        site = getattr(frappe.local, "site", None) or "Unknown"
    except Exception:
        site = "Unknown"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sid": sid,
        "site": site,
    }
