# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar, Optional

import frappe
from socketio import AsyncNamespace
from socketio.exceptions import ConnectionRefusedError

from fraxis.runtime.frappe_executor import run_frappe
from fraxis.security.auth import resolve_token_to_user


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FraxisNamespace(AsyncNamespace):
    """
    Base class for all Fraxis namespaces.

    Provides:
    - Decorator-based event handler registry (solves the colon-in-event-name problem)
    - Authenticated connection lifecycle (api_key:secret → bound per-connection user)
    - Per-operation identity helpers and a state-event emit convenience
    """

    _handler_map: ClassVar[dict[str, str]] = {}

    @classmethod
    def handler(cls, event: str) -> Callable:
        """Register a method as the handler for an event name that may contain colons."""
        def decorator(fn: Callable) -> Callable:
            fn.__fraxis_handler_event__ = event
            if hasattr(cls, "_handler_map") and isinstance(cls._handler_map, dict):
                cls._handler_map[event] = fn.__name__
            return fn
        return decorator

    async def trigger_event(self, event: str, *args) -> Any:
        """Dispatch colon-named events via the handler registry, then fall back.

        ``asyncio.CancelledError`` is propagated, never swallowed: when a client
        disconnects mid-operation the coroutine must unwind so the per-operation Frappe
        context (in the executor thread) runs its rollback/destroy (analysis S2-7).
        """
        if len(args) < 2:
            args = args + ({},) if len(args) == 1 else args

        method_name = self._handler_map.get(event) if hasattr(self, "_handler_map") else None
        if method_name:
            method = getattr(self, method_name, None)
            if method:
                if asyncio.iscoroutinefunction(method):
                    return await method(*args)
                return method(*args)

        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if callable(attr) and getattr(attr, "__fraxis_handler_event__", None) == event:
                if asyncio.iscoroutinefunction(attr):
                    return await attr(*args)
                return attr(*args)

        return await super().trigger_event(event, *args)

    # --- Authentication / identity ------------------------------------------------

    async def _authenticate(self, auth: Optional[dict]) -> str:
        """Resolve the connection's api_key:secret token to a user (off the loop)."""
        token = (auth or {}).get("token")
        return await run_frappe(resolve_token_to_user, token, user="Administrator")

    async def session_user(self, sid: str) -> Optional[str]:
        """Return the authenticated user bound to this sid, or None."""
        session = await self.get_session(sid)
        return (session or {}).get("user")

    async def require_user(self, sid: str) -> str:
        """Return the authenticated user or raise — the gate for every operation."""
        user = await self.session_user(sid)
        if not user or user == "Guest":
            raise frappe.PermissionError("Not authenticated")
        return user

    async def on_connect(self, sid: str, environ: dict, auth: dict = None) -> None:
        """Authenticate and bind the user to the connection.

        Lifecycle: system:connect:admit → [auth] → system:connect:success → ready,
        or system:connect:failure + ConnectionRefusedError on failure.
        """
        await self.emit("system:connect:admit", {}, to=sid)

        try:
            user = await self._authenticate(auth)
        except Exception:
            await self.emit("system:connect:failure", {"error": "Authentication failed"}, to=sid)
            raise ConnectionRefusedError("Authentication failed")

        await self.save_session(sid, {"user": user})
        await self.emit("system:connect:success", {}, to=sid)

        site = getattr(frappe.local, "site", None) or "Unknown"
        await self.emit(
            "system:connect:ready",
            {"site": site, "user": user, "timestamp": _utc_now_iso()},
            to=sid,
        )

    async def on_disconnect(self, sid: str, reason: str = None) -> None:
        """Standard disconnection handler."""
        pass

    async def _emit_state(
        self,
        sid: str,
        scope: str,
        action: str,
        state: str,
        payload: dict = None,
    ) -> None:
        """Emit a ``<scope>:<action>:<state>`` lifecycle event to a specific client."""
        await self.emit(f"{scope}:{action}:{state}", payload or {}, to=sid)

    # --- Permission-aware broadcast ------------------------------------------------

    async def emit_to_permitted(
        self,
        event: str,
        payload: dict,
        *,
        doctype: str,
        room: str,
        namespace: str,
    ) -> None:
        """Broadcast ``event`` to ``room``, re-checking read permission per recipient.

        Permission is verified once at subscribe time, but a user's access can be
        revoked afterwards. This re-validates each subscriber's bound user against
        ``frappe.has_permission(doctype, "read")`` at emit time, so a revoked user
        stops receiving change events on the very next broadcast — without needing to
        reconnect (analysis S3-3, §7.5).

        Doctype-level read is used (not row-level) so the same check is valid for the
        delete broadcast, whose document no longer exists. One permission check is run
        per distinct user (off the loop, in the executor), not per sid.

        Enumerates this server instance's local room participants; in a multi-server
        deployment each instance filters the subscribers it owns.
        """
        try:
            participants = list(self.server.manager.get_participants(namespace, room))
        except Exception:
            participants = []
        if not participants:
            return

        user_sids: dict[str, list] = {}
        for sid, _eio in participants:
            try:
                session = await self.server.get_session(sid, namespace=namespace)
            except Exception:
                session = None
            user = (session or {}).get("user")
            if user and user != "Guest":
                user_sids.setdefault(user, []).append(sid)
        if not user_sids:
            return

        users = list(user_sids)
        verdicts = await asyncio.gather(
            *[run_frappe(frappe.has_permission, doctype, "read", user=u) for u in users],
            return_exceptions=True,
        )
        for user, ok in zip(users, verdicts):
            if ok is True:
                for sid in user_sids[user]:
                    await self.emit(event, payload, to=sid, namespace=namespace)
