# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Progress publishing from fraxis RQ workers.

A method enqueued on the dedicated ``fraxis`` queue may stream progress by calling
:func:`publish_progress`. The event is published once, to the canonical per-task room
``method:{method}:{task_id}`` on the ``fraxis`` channel, via the synchronous write-only
``RedisManager`` (analysis §5.3c). There is no dual-publish to Frappe's standard realtime
channel and no hand-pickled message construction.

Progress is honoured only for methods registered ``@fraxis_method(realtime=True)``; for a
plain whitelisted method (start + end only), ``publish_progress`` is a deliberate no-op
(analysis §5b).
"""

from typing import Any, Optional

import frappe

from fraxis.registry import is_realtime
from fraxis.runtime.emitter import emit
from fraxis.services.validation import task_room


def _resolve_job_context(task_id, method_name):
    """Fill in task_id / method_name from the running RQ job when not supplied."""
    if task_id is not None and method_name is not None:
        return task_id, method_name

    job = None
    try:
        from rq import get_current_job

        job = get_current_job()
    except Exception:
        job = None

    if task_id is None:
        task_id = getattr(job, "id", None)

    if method_name is None:
        local_job = getattr(frappe.local, "job", None)
        method_name = getattr(local_job, "method", None) if local_job else None
        if method_name is None and job is not None:
            method_name = getattr(job, "func_name", None)

    return task_id, method_name


def publish_progress(
    percent: Optional[float] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    data: Any = None,
    task_id: Optional[str] = None,
    method_name: Optional[str] = None,
) -> None:
    """Emit a ``method:enqueue:progress`` event for the current fraxis job.

    No-op when called outside a fraxis job context or for a method that is not a
    registered realtime method.
    """
    task_id, method_name = _resolve_job_context(task_id, method_name)

    if not task_id or not method_name:
        return

    if not is_realtime(method_name):
        # Plain whitelisted methods get start + end events only — never progress.
        return

    payload = {
        "task_id": task_id,
        "percent": percent,
        "title": title,
        "description": description,
        "data": data,
    }
    emit(
        "method:enqueue:progress",
        payload,
        namespace="/api/method",
        room=task_room(method_name, task_id),
    )
