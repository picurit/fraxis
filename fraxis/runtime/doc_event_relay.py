# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Document-event relay — the ASGI-server (egress) half of the bridge.

A single long-lived asyncio task subscribed to the dedicated ``fraxis:doc-events`` Redis
channel. For each change fact published by ``doc_event_bridge`` (in some Frappe web/worker
process), it re-broadcasts through the existing permission-gated ``emit_to_permitted`` —
now also applying each subscriber's per-room filter. This is the **exact** gate: even if
the publisher's cached registry snapshot was momentarily stale, only live room members
whose read permission *and* filter both pass receive the event
(``fraxis_improvements_plan.md`` §A.4).

Fail-safe lifecycle: one task owned by the server, reconnect-with-backoff on Redis drop,
per-message try/except (one bad message never kills the loop), and a clean cancel on
shutdown (no orphan task). ``pubsub.listen()`` is back-pressured — no unbounded buffer.
"""

import asyncio
import json

import frappe
import redis.asyncio as aioredis

from fraxis.runtime.doc_event_bridge import DOC_EVENTS_CHANNEL
from fraxis.runtime.emitter import fraxis_redis_url
from fraxis.services.validation import collection_room, document_room

DOCTYPE_NAMESPACE = "/api/doctype"
DOCUMENT_NAMESPACE = "/api/document"

_MAX_BACKOFF = 30.0


async def _broadcast_fact(ns_doctype, ns_document, fact: dict) -> None:
    """Map one change fact to fraxis rooms and emit through the permission+filter gate."""
    doctype = fact.get("doctype")
    name = fact.get("name")
    action = fact.get("action")
    data = fact.get("data") or {}
    if not doctype or not name or not action:
        return

    payload = {"doctype": doctype, "name": name, "action": action, "data": data}
    coll = collection_room(doctype)

    # Collection room (/api/doctype): document:created on create, document:changed always.
    if action == "create":
        await ns_doctype.emit_to_permitted(
            "document:created", payload,
            doctype=doctype, room=coll, namespace=DOCTYPE_NAMESPACE, filter_data=data,
        )
    await ns_doctype.emit_to_permitted(
        "document:changed", payload,
        doctype=doctype, room=coll, namespace=DOCTYPE_NAMESPACE, filter_data=data,
    )

    # Per-document room (/api/document): document:updated / document:deleted.
    if action in ("update", "delete"):
        event = "document:updated" if action == "update" else "document:deleted"
        await ns_document.emit_to_permitted(
            event, payload,
            doctype=doctype, room=document_room(doctype, name),
            namespace=DOCUMENT_NAMESPACE, filter_data=data,
        )


async def run_doc_event_relay(ns_doctype, ns_document) -> None:
    """Subscribe to the doc-events channel and fan facts out forever (until cancelled)."""
    backoff = 1.0
    while True:
        client = None
        pubsub = None
        try:
            client = aioredis.from_url(fraxis_redis_url())
            pubsub = client.pubsub()
            await pubsub.subscribe(DOC_EVENTS_CHANNEL)
            backoff = 1.0
            frappe.logger("fraxis.doc_relay").info(
                f"doc-event relay subscribed to {DOC_EVENTS_CHANNEL}"
            )
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    raw = msg.get("data")
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8")
                    fact = json.loads(raw)
                    await _broadcast_fact(ns_doctype, ns_document, fact)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    frappe.logger("fraxis.doc_relay").error(
                        f"doc-event relay failed to dispatch message: {frappe.get_traceback()}"
                    )
        except asyncio.CancelledError:
            await _safe_close(pubsub, client)
            raise
        except Exception:
            frappe.logger("fraxis.doc_relay").error(
                f"doc-event relay connection error: {frappe.get_traceback()}"
            )
            await _safe_close(pubsub, client)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)


async def _safe_close(pubsub, client) -> None:
    for closer in (
        (lambda: pubsub.aclose()) if pubsub is not None else None,
        (lambda: client.aclose()) if client is not None else None,
    ):
        if closer is None:
            continue
        try:
            await closer()
        except Exception:
            pass
