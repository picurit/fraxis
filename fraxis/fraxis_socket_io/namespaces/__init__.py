# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
from typing import ClassVar
from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.utils.cornerstone.response import Response
from datetime import datetime


class SystemNamespace(FraxisNamespace):
    """
    Handle system-level events: connection lifecycle, health checks, diagnostics.
    
    All clients should connect to /system first to receive system:connect:ready 
    before emitting operational events.
    """
    
    _handler_map: ClassVar[dict[str, str]] = {}

    @FraxisNamespace.handler('system:ping')
    async def on_system_ping(self, sid, data: dict = None) -> dict:
        """
        Handles system:ping from client.
        Emits: system:ping:start → system:ping:success
        Returns: Response<{ message: "pong" }>  (ACK)
        """
        if data is None:
            data = {}
        
        # Emit start state
        await self._emit_state(sid, 'system', 'ping', 'start')
        
        # Build response payload
        response_data = {'message': 'pong'}
        response_data.update(data)  # Echo back any extra fields
        
        try:
            timestamp = frappe.utils.now()
            site = frappe.local.site if hasattr(frappe, 'local') else 'Unknown'
        except:
            timestamp = datetime.now().isoformat()
            site = 'Unknown'
        
        metadata = {
            'timestamp': timestamp,
            'sid': sid,
            'site': site
        }
        
        response = Response.success(data=response_data, metadata=metadata)
        
        # Emit success state
        await self._emit_state(sid, 'system', 'ping', 'success', response.to_dict())
        
        # Return ACK
        return response.to_dict()

    @FraxisNamespace.handler('system:health')
    async def on_system_health(self, sid, data: dict = None) -> dict:
        """
        Handles system:health from client.
        Emits: system:health:start → system:health:success
        Returns: Response<{ status: "healthy" }>  (ACK)
        """
        if data is None:
            data = {}
        
        # Emit start state
        await self._emit_state(sid, 'system', 'health', 'start')
        
        # Build response payload
        response_data = {'status': 'healthy'}
        
        try:
            timestamp = frappe.utils.now()
            site = frappe.local.site if hasattr(frappe, 'local') else 'Unknown'
        except:
            timestamp = datetime.now().isoformat()
            site = 'Unknown'
        
        metadata = {
            'timestamp': timestamp,
            'sid': sid,
            'site': site
        }
        
        response = Response.success(data=response_data, metadata=metadata)
        
        # Emit success state
        await self._emit_state(sid, 'system', 'health', 'success', response.to_dict())
        
        # Return ACK
        return response.to_dict()
