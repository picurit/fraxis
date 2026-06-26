# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Per-job RQ completion callbacks for fraxis enqueued methods.

These are passed as ``on_success`` / ``on_failure`` to ``frappe.enqueue`` for the
specific fraxis job — NOT registered as a bench-global ``after_job`` hook. RQ invokes
them in the worker process with the real outcome, giving honest success/failure
discrimination (fixes the always-success bug, analysis S2-4/S1-6) and emitting each
terminal event exactly once to the canonical per-task room (fixes duplicate delivery,
analysis S2-5).

``frappe.utils.background_jobs.execute_job`` tears down the Frappe context in its
``finally`` block before these callbacks run, so each callback re-initialises a minimal
context (just enough to read ``frappe.conf`` for the Redis URL) from ``job.kwargs['site']``.
"""

from typing import Optional

import frappe

from fraxis.runtime.emitter import emit
from fraxis.services.validation import task_room


def _method_name(job) -> Optional[str]:
    """Dotted method name the job ran, taken from execute_job's queue args."""
    kwargs = getattr(job, "kwargs", None) or {}
    method = kwargs.get("method")
    if callable(method):
        return f"{method.__module__}.{method.__qualname__}"
    return method


def _emit_terminal(job, state: str, payload: dict) -> None:
    method_name = _method_name(job)
    task_id = getattr(job, "id", None)
    if not method_name or not task_id:
        return

    inited = False
    try:
        if not getattr(frappe.local, "site", None):
            site = (getattr(job, "kwargs", None) or {}).get("site")
            if site:
                frappe.init(site=site)
                inited = True
        emit(
            f"method:enqueue:{state}",
            {"task_id": task_id, **payload},
            namespace="/api/method",
            room=task_room(method_name, task_id),
        )
    finally:
        if inited:
            frappe.destroy()


def on_job_success(job, connection, result) -> None:
    """RQ on_success(job, connection, result) — emit the terminal success event."""
    try:
        _emit_terminal(job, "success", {"result": result})
    except Exception:
        _log_callback_error()


def on_job_failure(job, connection, exc_type=None, exc_value=None, traceback=None) -> None:
    """RQ on_failure(job, connection, type, value, tb) — emit the terminal failure event.

    Also chains Frappe's default failed-registry truncation, which our custom callback
    would otherwise replace, keeping the RQ failed-job registry bounded.
    """
    try:
        error = str(exc_value) if exc_value else (
            exc_type.__name__ if exc_type else "Job failed"
        )
        _emit_terminal(
            job,
            "failure",
            {"error": error, "error_code": "METHOD_ENQUEUE_FAILED"},
        )
    except Exception:
        _log_callback_error()
    finally:
        try:
            from frappe.utils.background_jobs import truncate_failed_registry

            truncate_failed_registry(job, connection, exc_type, exc_value, traceback)
        except Exception:
            _log_callback_error()


def _log_callback_error() -> None:
    try:
        frappe.logger("fraxis.job_hooks").error(frappe.get_traceback())
    except Exception:
        pass
