# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Example methods showcasing the fraxis execution model.

Three classes of method are demonstrated:

1. Plain ``@frappe.whitelist()`` (test_get_list / test_get_value / test_count) — invokable
   through ``method:execute`` but NOT realtime: they emit start + end events only.
2. ``@fraxis_method(execution="async", ...)`` — coroutines / async-generators that run on
   the event loop. Any Frappe ORM they touch is offloaded via ``run_frappe`` so the loop
   is never blocked and each ORM op runs in its own connection/transaction (analysis §6.4).
3. ``@fraxis_method(execution="sync", realtime=True)`` — long-running sync work offloaded
   to the dedicated ``fraxis`` RQ worker, streaming progress via ``publish_progress``.

Realtime progress is granted by the registry flag, never by signature shape (analysis §5b).
"""

import asyncio
import random
from datetime import datetime
from typing import AsyncIterator, List

import frappe
import frappe.client  # bind the lazily-loaded submodule so frappe.client.* resolves in the bare executor thread (analysis Part B)

from fraxis.registry import fraxis_method
from fraxis.runtime.frappe_executor import run_frappe


# ============================================================================
# PLAIN WHITELISTED METHODS (start + end only — no realtime progress)
# ============================================================================

@frappe.whitelist()
def test_get_list(doctype, limit_page_length=20, limit_start=0, filters=None, fields=None):
    """Plain whitelisted list wrapper (exercises the start + end-only path)."""
    return frappe.client.get_list(
        doctype,
        limit_page_length=limit_page_length,
        limit_start=limit_start,
        filters=filters,
        fields=fields,
    )


@frappe.whitelist()
def test_get_value(doctype, name, fieldname=None):
    """Plain whitelisted single-document getter."""
    return frappe.client.get_value(doctype, name, fieldname)


@frappe.whitelist()
def test_count(doctype, filters=None):
    """Plain whitelisted count."""
    return frappe.db.count(doctype, filters)


# ============================================================================
# ASYNC FRAXIS METHODS (method:execute — run on the event loop)
# ============================================================================

@frappe.whitelist()
@fraxis_method(execution="async", realtime=False)
async def async_simple_operation(value: int = 1) -> dict:
    """Simple async method with simulated I/O delay (no ORM, no progress)."""
    await asyncio.sleep(0.5)
    return {"input": value, "output": int(value) * 2, "operation": "multiply_by_2", "async": True}


@frappe.whitelist()
@fraxis_method(execution="async", realtime=False)
async def async_frappe_orm_operation(doctype: str, limit: int = 5) -> dict:
    """Async method with Frappe ORM offloaded off the loop via run_frappe."""
    await asyncio.sleep(0.1)
    count = await run_frappe(frappe.db.count, doctype)
    docs = await run_frappe(frappe.get_all, doctype, fields=["name"], limit_page_length=limit)
    await asyncio.sleep(0.1)
    return {"doctype": doctype, "total_count": count, "sample_docs": docs, "limit": limit, "async": True}


@frappe.whitelist()
@fraxis_method(execution="async", realtime=False)
async def async_concurrent_operations(doctypes=None) -> dict:
    """Concurrent async ORM: each count runs in its own off-loop transaction."""
    if doctypes is None:
        doctypes = ["ToDo", "User", "DocType"]

    async def process_doctype(dt):
        await asyncio.sleep(0.2)
        try:
            return {dt: await run_frappe(frappe.db.count, dt)}
        except Exception as e:
            return {"error": str(e), "doctype": dt}

    results = await asyncio.gather(*(process_doctype(dt) for dt in doctypes), return_exceptions=True)

    counts, errors = {}, []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            errors.append({"doctype": doctypes[i], "error": str(result)})
        elif isinstance(result, dict):
            (errors.append(result) if "error" in result else counts.update(result))

    return {"counts": counts, "errors": errors, "total_doctypes": len(doctypes), "async": True, "concurrent": True}


@frappe.whitelist()
@fraxis_method(execution="async", realtime=False)
async def async_mixed_operations(doctype: str, delay: float = 0.5) -> dict:
    """Async I/O mixed with off-loop Frappe ORM."""
    start_time = asyncio.get_event_loop().time()
    await asyncio.sleep(delay)
    count = await run_frappe(frappe.db.count, doctype)
    await asyncio.sleep(0.1)
    sample = await run_frappe(frappe.get_all, doctype, fields=["name"], limit_page_length=1)
    elapsed = asyncio.get_event_loop().time() - start_time
    return {
        "doctype": doctype,
        "count": count,
        "sample": sample,
        "elapsed_seconds": round(elapsed, 3),
        "delay_requested": delay,
        "async": True,
    }


@frappe.whitelist()
@fraxis_method(execution="async", realtime=False)
async def async_error_handling(should_fail: bool = False, error_type: str = "runtime") -> dict:
    """Async error handling demo (errors propagate to the failure envelope)."""
    if not should_fail:
        await asyncio.sleep(0.1)
        return {"status": "success", "message": "No error requested", "async": True}

    if error_type == "validation":
        raise frappe.ValidationError("Async validation error triggered")
    elif error_type == "permission":
        raise frappe.PermissionError("Async permission error triggered")
    elif error_type == "runtime":
        raise RuntimeError("Async runtime error triggered")
    elif error_type == "db":
        await run_frappe(frappe.get_doc, "NonExistentDocType", "fake-name")
        return {"status": "error", "async": True}
    else:
        raise ValueError(f"Unknown error_type: {error_type}")


@frappe.whitelist()
@fraxis_method(execution="async", realtime=True)
async def async_with_progress_simulation(steps: int = 5, progress=None) -> dict:
    """Async method with an injected progress callback (realtime in-loop streaming)."""
    steps = int(steps)
    results = []
    for i in range(steps):
        await asyncio.sleep(0.2)
        step_result = {"step": i + 1, "timestamp": datetime.now().isoformat(), "data": f"Step {i + 1} completed"}
        results.append(step_result)
        if progress:
            await progress(
                percent=round((i + 1) / steps * 100, 1),
                title="Processing Steps",
                description=f"Step {i + 1} of {steps}",
                data=step_result,
            )
    return {"total_steps": steps, "results": results, "async": True}


# ============================================================================
# ASYNC ITERATOR METHODS (method:execute — streamed as progress)
# ============================================================================

@frappe.whitelist()
@fraxis_method(execution="async", realtime=True)
async def get_async_iterator(values: List[str], min_ms: int = 100, max_ms: int = 300) -> AsyncIterator[str]:
    """Async generator yielding values with random delays (streamed incrementally)."""
    min_ms, max_ms = int(min_ms), int(max_ms)
    if min_ms < 0 or max_ms < 0:
        raise ValueError("min_ms and max_ms must be non-negative")
    if min_ms > max_ms:
        raise ValueError("min_ms must be <= max_ms")

    for value in values:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)
        yield value


@frappe.whitelist()
@fraxis_method(execution="async", realtime=True)
async def process_values(values: List[str], min_ms: int = 100, max_ms: int = 300, progress=None) -> dict:
    """Consume an async iterator and report progress per received value."""
    values_aiter = get_async_iterator(values, min_ms=min_ms, max_ms=max_ms)
    start_time = asyncio.get_event_loop().time()
    prev_time = start_time
    results = []

    async for value in values_aiter:
        now = asyncio.get_event_loop().time()
        delta_ms = (now - prev_time) * 1000.0
        result_entry = {"value": value, "delta_ms": round(delta_ms, 3), "timestamp": datetime.now().isoformat()}
        results.append(result_entry)
        if progress:
            await progress(
                percent=round((len(results) / len(values)) * 100, 1),
                title="Processing Values",
                description=f"Received value: {value} (+{delta_ms:.3f} ms)",
                data=result_entry,
            )
        prev_time = now

    total_elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000.0
    return {
        "total_values": len(values),
        "results": results,
        "total_elapsed_ms": round(total_elapsed_ms, 3),
        "async": True,
        "async_iterator": True,
    }


# ============================================================================
# SYNC FRAXIS METHOD (method:enqueue — runs in the dedicated fraxis RQ worker)
# ============================================================================

@frappe.whitelist()
@fraxis_method(execution="sync", realtime=True)
def long_running_sync_job(iterations: int = 10) -> dict:
    """Long-running sync job; streams progress from the worker via publish_progress."""
    import time

    from fraxis.utils.realtime import publish_progress

    iterations = int(iterations)
    results = []
    for i in range(iterations):
        time.sleep(0.5)
        iteration_result = {"iteration": i + 1, "timestamp": datetime.now().isoformat()}
        results.append(iteration_result)
        publish_progress(
            percent=round((i + 1) / iterations * 100, 1),
            title="Processing Long Job",
            description=f"Completed iteration {i + 1} of {iterations}",
            data=iteration_result,
        )
    return {"total_iterations": iterations, "results": results, "completed": True}


@frappe.whitelist()
@fraxis_method(execution="sync", realtime=True)
def failing_sync_job(message: str = "intentional failure") -> dict:
    """A sync job that always raises — used to verify the enqueue failure path (S1-6)."""
    raise RuntimeError(message)
