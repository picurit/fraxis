# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

from typing import ClassVar

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.fraxis_socket_io.context import build_metadata
from fraxis.utils.cornerstone.response import Response


class SystemNamespace(FraxisNamespace):
    """
    System-level events: connection lifecycle, health checks, diagnostics.

    Clients connect to /system first and wait for system:connect:ready (emitted by the
    authenticated connection lifecycle in FraxisNamespace.on_connect) before emitting
    operational events on other namespaces.
    """

    _handler_map: ClassVar[dict[str, str]] = {}

    @FraxisNamespace.handler("system:ping")
    async def on_system_ping(self, sid, data: dict = None) -> dict:
        data = data or {}
        await self._emit_state(sid, "system", "ping", "start")
        response_data = {"message": "pong"}
        response_data.update(data)  # echo back extra fields
        response = Response.success(data=response_data, metadata=build_metadata(sid))
        await self._emit_state(sid, "system", "ping", "success", response.to_dict())
        return response.to_dict()

    @FraxisNamespace.handler("system:health")
    async def on_system_health(self, sid, data: dict = None) -> dict:
        await self._emit_state(sid, "system", "health", "start")
        response = Response.success(data={"status": "healthy"}, metadata=build_metadata(sid))
        await self._emit_state(sid, "system", "health", "success", response.to_dict())
        return response.to_dict()
