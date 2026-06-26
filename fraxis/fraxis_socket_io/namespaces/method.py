# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import asyncio
import inspect
from typing import ClassVar

import frappe

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.fraxis_socket_io.context import build_metadata
from fraxis.registry import get_fraxis_method
from fraxis.runtime.frappe_executor import run_frappe, set_current_user
from fraxis.services.validation import method_room, require, sanitize_error, task_room
from fraxis.utils.cornerstone.response import Response

NAMESPACE = "/api/method"


class MethodNamespace(FraxisNamespace):
    """
    Execute methods through the dual fraxis model (analysis §5b, §5c):

    - ``method:execute`` runs ``@fraxis_method(execution="async")`` coroutines /
      async-generators on the event loop (ORM offloaded via ``run_frappe``), and plain
      sync callables inside the executor.
    - ``method:enqueue`` offloads ``@fraxis_method(execution="sync")`` (and any plain
      whitelisted) methods to the dedicated ``fraxis`` RQ worker.

    Realtime progress is granted ONLY to methods registered ``@fraxis_method(realtime=
    True)`` — never inferred from a ``progress`` parameter or an async-generator shape. A
    plain whitelisted method may still be invoked but receives start + end events only.
    """

    _handler_map: ClassVar[dict[str, str]] = {}

    def _resolve_method(self, method_name: str):
        """Resolve a dotted path to ``(fn, meta)``.

        Metadata-only work (import, hooks, whitelist check) — safe on the loop thread.
        Importing the target module triggers any ``@fraxis_method`` registration, so the
        registry is consulted after resolution. Non-registered methods must still be
        ``frappe.is_whitelisted`` to be permitted, and are treated as realtime=False.
        """
        overrides = frappe.get_hooks("override_whitelisted_methods") or {}
        target = overrides.get(method_name, method_name)
        fn = frappe.get_attr(target)

        meta = get_fraxis_method(method_name)
        if meta is not None:
            return fn, {**meta, "registered": True}

        # Plain whitelisted method: permitted to execute, but never realtime.
        frappe.is_whitelisted(fn)  # raises PermissionError if not whitelisted
        execution = "async" if asyncio.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn) else "sync"
        return fn, {"fn": fn, "execution": execution, "realtime": False, "queue": "fraxis", "registered": False}

    def _make_progress_cb(self, sid):
        async def _progress(percent=None, title=None, description=None, data=None):
            payload = {"percent": percent, "title": title, "description": description, "data": data}
            # Delivered to the calling client ONLY. method:execute is a synchronous
            # request/response; broadcasting one caller's progress to a shared method
            # room would (a) disclose it to every other subscriber — a cross-user data
            # leak — and (b) double-deliver to a caller that also subscribed
            # (analysis §7 security model, S2-5 single-delivery).
            await self._emit_state(sid, "method", "execute", "progress", payload)
        return _progress

    async def _stream_async_gen(self, agen, sid, method_name, progress_cb):
        """Consume an async generator, streaming each value as progress (bounded memory).

        Values are emitted incrementally rather than buffered; the ACK carries only a
        summary so a large stream never accumulates in memory (analysis S4-5).
        """
        count = 0
        async for value in agen:
            count += 1
            if progress_cb is not None:
                await progress_cb(
                    percent=None,
                    title="Stream",
                    description=f"value {count}",
                    data={"value": value, "index": count - 1},
                )
        return {"total_count": count, "streamed": True}

    @FraxisNamespace.handler("method:execute")
    async def on_method_execute(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        method_name = data.get("method")
        try:
            user = await self.require_user(sid)
            args = data.get("args", {})
            require(data, "method")
            if not isinstance(args, dict):
                raise TypeError("args must be a dictionary")

            await self._emit_state(sid, "method", "execute", "start")
            fn, meta = self._resolve_method(method_name)
            realtime = bool(meta.get("realtime"))

            # Bind identity for any ORM the (async) method offloads via run_frappe.
            set_current_user(user)

            # frappe.whitelist wraps with a SYNC wrapper that hides async-ness; the true
            # function is reached via inspect.unwrap (functools.wraps sets __wrapped__).
            real = inspect.unwrap(fn)
            is_coro = asyncio.iscoroutinefunction(real)
            is_async_gen = inspect.isasyncgenfunction(real)
            # An async method runs on the event loop. If it is not fraxis-registered there
            # is no contract that its Frappe ORM is offloaded via run_frappe, so a stray
            # blocking call would freeze every connected client. Only registered async
            # methods may run on the loop (analysis §6.4); plain whitelisted methods must
            # be sync and run in the executor below.
            if (is_coro or is_async_gen) and not meta.get("registered"):
                raise PermissionError(
                    f"Async method '{method_name}' must be registered with @fraxis_method "
                    "to execute on the event loop"
                )
            progress_cb = self._make_progress_cb(sid) if (realtime and (is_coro or is_async_gen)) else None

            call_args = dict(args)
            if realtime and is_coro and "progress" in inspect.signature(real).parameters:
                call_args["progress"] = progress_cb

            if is_async_gen:
                result = await self._stream_async_gen(fn(**call_args), sid, method_name, progress_cb)
            elif is_coro:
                result = await fn(**call_args)
            else:
                # Plain sync callable: run in the executor (own context + transaction).
                result = await run_frappe(fn, user=user, **call_args)

            response = Response.success(data=result, metadata=metadata)
            # Terminal event to the calling client only (see _make_progress_cb): the result
            # belongs to the caller and must not be broadcast to other method subscribers.
            await self._emit_state(sid, "method", "execute", "success", response.to_dict())
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "execute", "METHOD_EXECUTE_FAILED", e, method_name, metadata)

    @FraxisNamespace.handler("method:enqueue")
    async def on_method_enqueue(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        method_name = data.get("method")
        try:
            user = await self.require_user(sid)
            args = data.get("args", {})
            require(data, "method")
            if not isinstance(args, dict):
                raise TypeError("args must be a dictionary")

            await self._emit_state(sid, "method", "enqueue", "start")
            _, meta = self._resolve_method(method_name)
            queue = meta.get("queue", "fraxis")

            task_id = await run_frappe(_enqueue_fraxis_job, method_name, queue, args, user=user)

            # Join ONLY the canonical per-task room so each terminal/progress event is
            # delivered exactly once (analysis S2-5).
            await self.enter_room(sid, task_room(method_name, task_id))

            response_data = {"task_id": task_id}
            # Acceptance is a distinct event from completion (analysis S2-6).
            await self._emit_state(
                sid, "method", "enqueue", "accepted",
                {**Response.success(data=response_data, metadata=metadata).to_dict(), "data": response_data},
            )
            return Response.success(data=response_data, metadata=metadata).to_dict()
        except Exception as e:
            return await self._fail(sid, "enqueue", "METHOD_ENQUEUE_FAILED", e, method_name, metadata)

    @FraxisNamespace.handler("method:subscribe")
    async def on_method_subscribe(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        method_name = data.get("method")
        try:
            await self.require_user(sid)
            require(data, "method")
            # Resolve to confirm the method exists and is permitted before subscribing.
            self._resolve_method(method_name)
            room = method_room(method_name)
            await self.enter_room(sid, room)
            return Response.success(
                data={"subscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "subscribe", "METHOD_SUBSCRIBE_FAILED", e, method_name, metadata, emit=False)

    @FraxisNamespace.handler("method:unsubscribe")
    async def on_method_unsubscribe(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        method_name = data.get("method")
        try:
            await self.require_user(sid)
            require(data, "method")
            room = method_room(method_name)
            await self.leave_room(sid, room)
            return Response.success(
                data={"unsubscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "unsubscribe", "METHOD_UNSUBSCRIBE_FAILED", e, method_name, metadata, emit=False)

    async def _fail(self, sid, action, code, exc, method_name, metadata, emit=True):
        # File-based logger (not frappe.log_error) on purpose: this runs on the event
        # loop, where a DB insert+commit would block it and reuse the shared boot
        # connection (analysis S1-1/S2-1, §6). Traceback kept server-side via exc_info.
        frappe.logger("fraxis.method").error(
            f"method:{action} failed for {method_name}: {exc}", exc_info=True
        )
        response = Response.failure(
            error=sanitize_error(exc),
            error_code=code,
            details={"method": method_name},
            metadata=metadata,
        )
        if emit:
            await self._emit_state(sid, "method", action, "failure", response.to_dict())
        return response.to_dict()


def _enqueue_fraxis_job(method_name: str, queue: str, args: dict) -> str:
    """Enqueue on the dedicated fraxis queue with per-job terminal callbacks.

    Runs inside the executor (authenticated user is set), so the job inherits that user
    and executes with the same permissions. Returns the RQ job id (the task_id).
    """
    job = frappe.enqueue(
        method_name,
        queue=queue,
        on_success="fraxis.utils.job_hooks.on_job_success",
        on_failure="fraxis.utils.job_hooks.on_job_failure",
        **(args or {}),
    )
    return job.id
