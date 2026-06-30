# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Subscription registry — the activation gate for the document-event bridge.

Two processes cooperate across Redis:

* The **ASGI server process** (namespace handlers) records who is subscribed to what,
  by incrementing reference counts in two Redis hashes at subscribe time and
  decrementing them at unsubscribe / disconnect time.
* The **Frappe web / worker processes** (where ORM writes happen) consult an in-process
  *cached snapshot* of those hashes before doing any bridge work. If nobody is
  subscribed to the affected doctype/document, ``publish_doc_event`` returns immediately
  with zero Redis traffic (``fraxis_improvements_plan.md`` §A.2).

Reference counts (not a set) so the gate deactivates only when the *last* subscriber for
a target leaves; ``HINCRBY`` is atomic and race-free across workers, and ``sub_del``
clamps at zero so a hash field is never left negative or as a zombie.

The snapshot is refreshed at most once per ``_SNAPSHOT_TTL`` seconds, so the hot
``doc_events`` path on every ORM write is a dict lookup, not a Redis round-trip. A stale
snapshot is safe: a just-subscribed target may be missed for up to one TTL (the relay's
exact per-recipient gate still delivers correctly once published), and a just-emptied
target may over-publish for up to one TTL (the relay then delivers to nobody).
"""

import threading
import time
from typing import Optional

from redis import Redis

from fraxis.runtime.emitter import fraxis_redis_url

H_DT = "fraxis:subs:doctype"
H_DOC = "fraxis:subs:document"

_SNAPSHOT_TTL = 1.0

_client: Optional[Redis] = None
_client_lock = threading.Lock()

_snap_lock = threading.Lock()
_snap_ts: float = 0.0
_snap_dt: dict[str, int] = {}
_snap_doc: dict[str, int] = {}


def doc_key(doctype: str, name: str) -> str:
    """Field key for a per-document subscription in the ``H_DOC`` hash."""
    return f"{doctype}::{name}"


def _redis() -> Redis:
    """Process-global registry client (decoded responses, pooled, thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = Redis.from_url(fraxis_redis_url(), decode_responses=True)
    return _client


def sub_add(h: str, key: str) -> None:
    """Increment the refcount for ``key`` in hash ``h`` (atomic)."""
    _redis().hincrby(h, key, 1)


def sub_del(h: str, key: str) -> None:
    """Decrement the refcount for ``key``; remove the field when it reaches zero."""
    if _redis().hincrby(h, key, -1) <= 0:
        _redis().hdel(h, key)


def _coerce_counts(raw: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for field, value in (raw or {}).items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[field] = count
    return out


def _snapshot() -> tuple[dict[str, int], dict[str, int]]:
    """Return the cached (doctype, document) refcount maps, refreshing if stale."""
    global _snap_ts, _snap_dt, _snap_doc
    now = time.monotonic()
    if now - _snap_ts < _SNAPSHOT_TTL:
        return _snap_dt, _snap_doc
    with _snap_lock:
        if now - _snap_ts < _SNAPSHOT_TTL:
            return _snap_dt, _snap_doc
        try:
            client = _redis()
            dt = _coerce_counts(client.hgetall(H_DT))
            doc = _coerce_counts(client.hgetall(H_DOC))
            _snap_dt, _snap_doc, _snap_ts = dt, doc, now
        except Exception:
            # On Redis trouble, keep the previous snapshot but bump the timestamp so we
            # do not hammer a dead Redis on every ORM write. Worst case the gate is
            # briefly stale; the relay's exact gate still protects correctness.
            _snap_ts = now
    return _snap_dt, _snap_doc


def is_active(doctype: str, name: Optional[str] = None) -> bool:
    """True if a collection-level or per-document subscription currently exists."""
    dt_map, doc_map = _snapshot()
    if doctype in dt_map:
        return True
    if name is not None and doc_key(doctype, name) in doc_map:
        return True
    return False
