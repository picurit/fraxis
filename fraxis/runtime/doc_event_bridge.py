# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Document-event bridge — the Frappe-process (ingress) half.

Registered as ``doc_events`` for the ``"*"`` wildcard (Frappe requires static hook
registration), these shims fire on every ORM insert/update/delete across all apps. The
**first action is the subscription gate**: a cached registry lookup (``sub_registry``,
~microseconds). If nobody is subscribed to the affected collection or document, the shim
returns immediately — no Redis publish, no work. Only subscribed targets produce a fact.

When active, the document is projected to its in-source field allowlist
(``bridge_projection``) and published as a JSON fact to a *dedicated* Redis channel
(``fraxis:doc-events``) — never ``frappe.publish_realtime`` and never the worker channel
``fraxis``. The relay (ASGI server side) re-broadcasts it through the permission- and
filter-gated ``emit_to_permitted``.

The publish is **fire-and-forget**: any failure is logged and swallowed so the bridge can
never break the writing transaction of the app that triggered it
(``fraxis_improvements_plan.md`` §A.3, well_frappe_coding.md §14.7).
"""

import json
import threading
from typing import Optional

import frappe
from redis import Redis

from fraxis.runtime import sub_registry
from fraxis.runtime.bridge_projection import json_fields, project_fields
from fraxis.runtime.emitter import fraxis_redis_url

DOC_EVENTS_CHANNEL = "fraxis:doc-events"

_publisher: Optional[Redis] = None
_pub_lock = threading.Lock()


def _redis() -> Redis:
    """Process-global publisher client (pooled, thread-safe)."""
    global _publisher
    if _publisher is None:
        with _pub_lock:
            if _publisher is None:
                _publisher = Redis.from_url(fraxis_redis_url())
    return _publisher


def _project(doc) -> dict:
    fields = project_fields(doc.doctype)
    if not fields:
        return {}
    jf = json_fields(doc.doctype)
    data: dict = {}
    for field in fields:
        value = doc.get(field)
        if field in jf and isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
        data[field] = value
    return data


def publish_doc_event(doc, action: str) -> None:
    """Publish a change fact for ``doc`` iff a subscriber is listening. Never raises."""
    try:
        # In-band fraxis CRUD writes are already broadcast by their socket handler; skip
        # the bridge for them so subscribed collections are not double-emitted.
        if getattr(frappe.flags, "fraxis_inband", False):
            return
        doctype = doc.doctype
        name = doc.name
        if not sub_registry.is_active(doctype, name):  # THE GATE — dormant by default
            return
        fact = {
            "doctype": doctype,
            "name": name,
            "action": action,
            "data": _project(doc),
        }
        _redis().publish(DOC_EVENTS_CHANNEL, json.dumps(fact, default=str))
    except Exception:
        try:
            frappe.logger("fraxis.doc_bridge").error(frappe.get_traceback())
        except Exception:
            pass


# --- doc_events shims (standard Frappe (doc, method) signature) ----------------------

def on_after_insert(doc, method=None) -> None:
    publish_doc_event(doc, "create")


def on_update(doc, method=None) -> None:
    # Frappe's insert() also runs on_update (within run_post_save_methods) with
    # doc.flags.in_insert set. after_insert already emitted the "create" fact, so skip
    # this redundant "update" during the insert path — avoids double-emitting every insert.
    if getattr(getattr(doc, "flags", None), "in_insert", False):
        return
    publish_doc_event(doc, "update")


def on_trash(doc, method=None) -> None:
    publish_doc_event(doc, "delete")
