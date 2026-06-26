# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Cross-process Socket.IO emitter for synchronous RQ workers.

RQ workers are synchronous and have no event loop, so they cannot use the server's
``AsyncRedisManager``. python-socketio ships a synchronous ``RedisManager`` whose
``write_only`` mode publishes pickle-encoded messages to the same Redis channel the
async server listens on — wire-compatible, no private format reverse-engineering, one
persistent connection (replaces the per-tick ``Redis.from_url`` churn and the
hand-pickled message dicts of the old implementation).

The manager is a process-global singleton built lazily under a lock (well_frappe_coding
.md §12 / P9). Publisher (worker) and subscriber (ASGI server) must agree on both the
Redis URL and the channel — :func:`fraxis_redis_url` is the single source of truth for both.
"""

import threading
from typing import Optional

import frappe
from socketio import RedisManager

FRAXIS_CHANNEL = "fraxis"

_manager: Optional[RedisManager] = None
_lock = threading.Lock()


def fraxis_redis_url() -> str:
    """Redis URL for the dedicated fraxis pub/sub channel.

    Prefers an explicit ``fraxis_redis`` conf key, then the dedicated (otherwise unused)
    ``redis_socketio`` broker, falling back to ``redis_queue``. Both the ASGI server's
    ``AsyncRedisManager`` and this write-only manager must resolve the same URL.
    """
    conf = frappe.conf
    return conf.get("fraxis_redis") or conf.get("redis_socketio") or conf.get("redis_queue")


def get_emitter() -> RedisManager:
    """Lazily build and cache the write-only Redis manager for this worker process."""
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = RedisManager(
                    url=fraxis_redis_url(),
                    channel=FRAXIS_CHANNEL,
                    write_only=True,
                    logger=False,
                )
    return _manager


def emit(event: str, data: dict, *, namespace: str, room: str) -> None:
    """Publish a Socket.IO event to a room on the fraxis channel. Never raises."""
    try:
        get_emitter().emit(event, data, namespace=namespace, room=room)
    except Exception:
        try:
            frappe.logger("fraxis.emitter").error(
                f"Failed to emit {event} to {room}: {frappe.get_traceback()}"
            )
        except Exception:
            pass
