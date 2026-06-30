# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Queue resolution with a graceful fallback to the shared ``default`` queue.

The dedicated ``fraxis`` RQ worker (``bench worker --queue fraxis``) only exists when the
operator has regenerated the Procfile / supervisor config *after* declaring
``workers.fraxis`` in ``common_site_config.json``. If that step is skipped the ``fraxis``
queue is either not a configured queue at all (``frappe.enqueue`` would raise) or it is
configured but has no live worker consuming it (jobs would sit in Redis forever, never
running).

To keep ``method:enqueue`` resilient we resolve the requested queue and fall back to
``default`` — which always has the standard ``bench worker`` consuming it — whenever the
requested queue is unavailable. Availability is validated once at server startup
(``socketio-server``) and cached for the lifetime of the process, so the cost is paid a
single time and every subsequent enqueue is a dict lookup.
"""

import threading

import frappe

FALLBACK_QUEUE = "default"

_lock = threading.Lock()
# requested queue name -> effective (possibly fallen-back) queue name
_resolved: dict[str, str] = {}


def _has_live_worker(queue: str) -> bool:
    """True only when ``queue`` is a configured queue AND has ≥1 live RQ worker.

    A configured-but-idle queue (declared in ``workers`` but with no worker process
    consuming it) is treated as unavailable: enqueuing onto it would accept the job and
    then leave it stranded. Any Redis / config error is treated as "unavailable" so the
    caller falls back rather than propagating an enqueue failure.
    """
    from frappe.utils.background_jobs import get_queue, get_workers

    try:
        # get_queue() runs validate_queue(): raises if `queue` is not a configured queue
        # (i.e. not short/default/long and not present in common_site_config workers).
        q = get_queue(queue)
        return len(get_workers(q)) > 0
    except Exception:
        return False


def resolve_queue(queue: str) -> str:
    """Return ``queue`` if it is available, else the ``default`` fallback queue.

    The decision is computed once per requested queue and cached for the process
    lifetime (see :func:`validate_startup_queue`, called from ``socketio-server``).
    """
    if queue == FALLBACK_QUEUE:
        return queue

    cached = _resolved.get(queue)
    if cached is not None:
        return cached

    with _lock:
        cached = _resolved.get(queue)
        if cached is None:
            cached = queue if _has_live_worker(queue) else FALLBACK_QUEUE
            _resolved[queue] = cached
    return cached


def validate_startup_queue(queue: str = "fraxis") -> str:
    """Validate ``queue`` availability at server startup and log the outcome.

    Invoked from the ``socketio-server`` command so operators can see, in the server log,
    whether the dedicated ``fraxis`` worker is consuming jobs or whether ``method:enqueue``
    will transparently fall back to the shared ``default`` queue. Returns the effective
    queue that enqueues will use.
    """
    effective = resolve_queue(queue)
    logger = frappe.logger("socketio_server")
    if effective == queue:
        logger.info(f"Queue '{queue}' is available — method:enqueue will dispatch to it")
    else:
        logger.warning(
            f"Queue '{queue}' has no live worker — method:enqueue will fall back to "
            f"'{effective}'. To enable the dedicated worker, declare it under 'workers' in "
            "common_site_config.json, then run `bench setup procfile` (dev) or `bench setup "
            "supervisor` (prod) and restart."
        )
    return effective


def _reset_cache() -> None:
    """Test helper: drop the cached queue-resolution decisions."""
    with _lock:
        _resolved.clear()
