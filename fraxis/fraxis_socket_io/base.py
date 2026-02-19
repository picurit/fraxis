# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import asyncio
import frappe
from socketio import AsyncNamespace
from socketio.exceptions import ConnectionRefusedError
from typing import ClassVar, Callable, Any
from fraxis.utils.cornerstone.response import Response


class FraxisNamespace(AsyncNamespace):
    """
    Base class for all Fraxis namespaces.

    Provides:
    - Decorator-based event handler registry (solves colon-in-event-name problem)
    - Standardized connection lifecycle with state event emission
    - Authentication hook (validate_auth — override in subclasses)
    - Convenience method _emit_state for sending lifecycle state events
    """

    _handler_map: ClassVar[dict[str, str]] = {}

    @classmethod
    def handler(cls, event: str) -> Callable:
        """
        Class decorator that registers a method as the handler for a
        specific event name. Allows event names with colons (e.g. 'document:create')
        to map to valid Python method names (e.g. 'on_document_create').

        Usage:
            @FraxisNamespace.handler('document:create')
            async def on_document_create(self, sid, data):
                ...

        Each concrete subclass must define its own _handler_map = {} to
        avoid cross-contamination between namespaces.
        """
        def decorator(fn: Callable) -> Callable:
            # Mark the function with the event it handles
            # This allows trigger_event to discover handlers dynamically
            fn.__fraxis_handler_event__ = event
            
            # Also try to register in the _handler_map if it exists and is mutable
            if hasattr(cls, '_handler_map') and isinstance(cls._handler_map, dict):
                cls._handler_map[event] = fn.__name__
            
            return fn
        return decorator

    async def trigger_event(self, event: str, *args) -> Any:
        """
        Override of AsyncNamespace.trigger_event.
        Checks _handler_map first, then searches for methods marked with @handler decorator,
        then falls back to default on_<event> resolution.
        This allows event names with colons to be properly dispatched.
        
        Handlers are expected to have signature: async def handler(self, sid, data=None)
        If Socket.IO passes incomplete args, we provide defaults.
        """
        # Ensure args has at least (sid, data) - if data is missing, provide empty dict
        if len(args) < 2:
            # args should be (sid, data) for most handlers
            # If only sid is provided, add empty dict as data
            args = args + ({},) if len(args) == 1 else args
        
        # Check if event is in the handler map (for colon-separated events)
        method_name = self._handler_map.get(event) if hasattr(self, '_handler_map') else None
        
        if method_name:
            method = getattr(self, method_name, None)
            if method:
                if asyncio.iscoroutinefunction(method):
                    try:
                        ret = await method(*args)
                    except asyncio.CancelledError:
                        ret = None
                else:
                    ret = method(*args)
                return ret
        
        # Dynamic search: look for methods marked with @handler decorator
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if callable(attr) and hasattr(attr, '__fraxis_handler_event__'):
                if getattr(attr, '__fraxis_handler_event__') == event:
                    if asyncio.iscoroutinefunction(attr):
                        try:
                            ret = await attr(*args)
                        except asyncio.CancelledError:
                            ret = None
                    else:
                        ret = attr(*args)
                    return ret
        
        # Fallback to default on_<event> resolution
        return await super().trigger_event(event, *args)

    def validate_auth(self, client_auth: dict) -> bool:
        """
        Override in subclasses to implement authentication logic.
        Return True to allow the connection, False to reject.
        """
        return True  # stub — always allow until implemented

    async def on_connect(self, sid: str, environ: dict, auth: dict = None) -> None:
        """
        Standard connection handler.
        Emits: system:connect:admit → [validate] → system:connect:success or :failure → system:connect:ready
        Raises: ConnectionRefusedError if authentication fails.
        """
        # Emit admit signal immediately
        await self.emit('system:connect:admit', {}, to=sid)
        
        # Validate authentication
        if not self.validate_auth(auth or {}):
            await self.emit('system:connect:failure', {'error': 'Authentication failed'}, to=sid)
            raise ConnectionRefusedError("Authentication failed")
        
        # Authentication successful
        await self.emit('system:connect:success', {}, to=sid)
        
        # Initialize session ready
        try:
            site_name = frappe.local.site if hasattr(frappe, 'local') and hasattr(frappe.local, 'site') else 'Unknown'
            user = frappe.session.user if hasattr(frappe, 'session') and hasattr(frappe.session, 'user') else 'Guest'
            timestamp = frappe.utils.now()
        except:
            site_name = 'Unknown'
            user = 'Guest'
            from datetime import datetime
            timestamp = datetime.now().isoformat()
        
        ready_payload = {
            'site': site_name,
            'user': user,
            'timestamp': timestamp
        }
        await self.emit('system:connect:ready', ready_payload, to=sid)

    async def on_disconnect(self, sid: str, reason: str = None) -> None:
        """Standard disconnection handler."""
        pass

    async def _emit_state(
        self,
        sid: str,
        scope: str,
        action: str,
        state: str,
        payload: dict = None
    ) -> None:
        """
        Convenience method to emit a <scope>:<action>:<state> event to a specific client.

        Example:
            await self._emit_state(sid, 'document', 'create', 'start')
            await self._emit_state(sid, 'document', 'create', 'success', response.to_dict())
        """
        event_name = f"{scope}:{action}:{state}"
        await self.emit(event_name, payload or {}, to=sid)
