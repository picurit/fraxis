# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Per-operation Frappe execution off the event loop.

The Socket.IO server runs a single asyncio event loop. Frappe's ``frappe.local``
(db connection, session, flags) is a ``werkzeug.local.Local`` — thread-local, not
coroutine-local — so a single connection shared across interleaved coroutines on the
loop thread corrupts transactions (well_frappe_coding.md §12).

This module isolates every blocking Frappe operation in its own thread, where it owns
a full ``init → connect → set_user → commit/rollback → destroy`` lifecycle. The loop
never touches a Frappe connection directly. A bounded thread pool provides natural
backpressure: when all workers are busy new operations queue instead of overwhelming
the database (well_frappe_coding.md §12.3).
"""

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any, Callable, Optional

import frappe

# Boot-captured context. Worker threads do not inherit the request/boot thread's
# frappe.local, so both the site and the sites path must be captured explicitly and
# replayed on every per-operation init (well_frappe_coding.md §12.2, S4-8).
_SITE: Optional[str] = None
_SITES_PATH: Optional[str] = None
_POOL: Optional[ThreadPoolExecutor] = None
_lock = threading.Lock()

# The authenticated user for the in-flight operation, carried on the event loop so that
# genuinely-async methods (which run on the loop) can offload ORM work through
# ``run_frappe`` without having to thread the identity through their own signatures.
_current_user: ContextVar[str] = ContextVar("fraxis_current_user", default="Guest")

DEFAULT_MAX_WORKERS = 16


def configure(site: str, sites_path: str, max_workers: Optional[int] = None) -> None:
    """Capture boot context and build the bounded executor. Call once at server start."""
    global _SITE, _SITES_PATH, _POOL
    with _lock:
        _SITE = site
        _SITES_PATH = sites_path
        if _POOL is None:
            workers = max_workers or DEFAULT_MAX_WORKERS
            _POOL = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="fraxis-frappe",
            )


def is_configured() -> bool:
    return _POOL is not None


def set_current_user(user: Optional[str]) -> None:
    """Bind the authenticated user to the current loop task (read by ``run_frappe``)."""
    _current_user.set(user or "Guest")


def get_current_user() -> str:
    return _current_user.get()


def _run(user: str, fn: Callable, args: tuple, kwargs: dict) -> Any:
    """One isolated Frappe unit of work: own connection, transaction and session."""
    frappe.init(site=_SITE, sites_path=_SITES_PATH)
    frappe.connect()
    try:
        frappe.set_user(user or "Guest")
        result = fn(*args, **kwargs)
        frappe.db.commit()
        return result
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()


async def run_frappe(fn: Callable, *args: Any, user: Optional[str] = None, **kwargs: Any) -> Any:
    """Run a blocking Frappe callable off the event loop in its own transaction.

    The user is resolved from the explicit ``user`` argument first, then from the
    loop-task context variable (set by the namespace handler at dispatch time).
    """
    if _POOL is None:
        raise RuntimeError("Fraxis frappe executor is not configured")
    resolved = user or _current_user.get()
    loop = asyncio.get_running_loop()
    call = functools.partial(_run, resolved, fn, args, kwargs)
    return await loop.run_in_executor(_POOL, call)


def shutdown(wait: bool = True) -> None:
    """Drain and dispose the executor. Registered for graceful server shutdown."""
    global _POOL
    with _lock:
        pool, _POOL = _POOL, None
    if pool is not None:
        pool.shutdown(wait=wait)
