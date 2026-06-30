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

from fraxis.runtime import sub_registry
from fraxis.runtime.frappe_executor import run_frappe
from fraxis.security.auth import resolve_token_to_user
from fraxis.services.event_filter import matches


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
        """Release every subscription refcount this sid held (critical cleanup).

        Without this, a refcount leaks on each disconnect, the activation gate stays
        stuck "active", and the bridge over-emits forever (fraxis_improvements_plan.md
        §A.2). The per-sid filter map is discarded with the session automatically.
        """
        try:
            session = await self.get_session(sid)
        except Exception:
            session = None
        subs = (session or {}).get("subs") or {}
        for room, hk in list(subs.items()):
            try:
                sub_registry.sub_del(hk[0], hk[1])
            except Exception:
                try:
                    frappe.logger("fraxis.sub_registry").error(frappe.get_traceback())
                except Exception:
                    pass

    # --- Subscription registry + per-sid filter bookkeeping -----------------------

    async def _track_subscription(
        self,
        sid: str,
        *,
        h: str,
        key: str,
        room: str,
        filter_clauses,
    ) -> None:
        """Record a subscription: store its filter on the session and bump the refcount.

        Re-subscribing the same room is idempotent on the refcount — the previous count
        for that room is released first so a client cannot inflate the gate by repeating
        ``subscribe`` on the same room.
        """
        session = await self.get_session(sid) or {}
        subs = dict(session.get("subs") or {})
        filters = dict(session.get("filters") or {})

        prev = subs.get(room)
        if prev:
            try:
                sub_registry.sub_del(prev[0], prev[1])
            except Exception:
                pass

        subs[room] = [h, key]
        if filter_clauses:
            filters[room] = filter_clauses
        else:
            filters.pop(room, None)

        session["subs"] = subs
        session["filters"] = filters
        await self.save_session(sid, session)

        try:
            sub_registry.sub_add(h, key)
        except Exception:
            try:
                frappe.logger("fraxis.sub_registry").error(frappe.get_traceback())
            except Exception:
                pass

    async def _untrack_subscription(self, sid: str, room: str) -> None:
        """Drop a room's filter from the session and decrement its refcount."""
        session = await self.get_session(sid) or {}
        subs = dict(session.get("subs") or {})
        filters = dict(session.get("filters") or {})
        prev = subs.pop(room, None)
        filters.pop(room, None)
        session["subs"] = subs
        session["filters"] = filters
        await self.save_session(sid, session)
        if prev:
            try:
                sub_registry.sub_del(prev[0], prev[1])
            except Exception:
                try:
                    frappe.logger("fraxis.sub_registry").error(frappe.get_traceback())
                except Exception:
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
        filter_data: dict = None,
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

        ``filter_data`` (the bridged document's projected fields) enables per-subscriber
        narrowing: a sid that subscribed with a ``filter`` only receives documents whose
        data matches its stored clauses. The filter is per-client, so it is evaluated per
        sid — *after* the per-user permission verdict — and can only narrow delivery
        within an already-permitted room, never widen it (fraxis_improvements_plan.md
        §A.4). When ``filter_data`` is ``None`` (in-process socket-handler broadcasts) no
        filtering occurs — original behavior, fully backward-compatible.

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
        sid_clauses: dict[str, list] = {}
        for sid, _eio in participants:
            try:
                session = await self.server.get_session(sid, namespace=namespace)
            except Exception:
                session = None
            user = (session or {}).get("user")
            if user and user != "Guest":
                user_sids.setdefault(user, []).append(sid)
                if filter_data is not None:
                    sid_clauses[sid] = ((session or {}).get("filters") or {}).get(room)
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
                    if filter_data is not None and not matches(sid_clauses.get(sid), filter_data):
                        continue
                    await self.emit(event, payload, to=sid, namespace=namespace)
