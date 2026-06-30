# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
from typing import ClassVar

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.fraxis_socket_io.context import build_metadata
from fraxis.runtime import sub_registry
from fraxis.runtime.frappe_executor import run_frappe
from fraxis.services import doctype as doctype_service
from fraxis.services.event_filter import normalize_filter
from fraxis.services.validation import clamp_limit, collection_room, require, sanitize_error
from fraxis.utils.cornerstone.response import Response


class DoctypeNamespace(FraxisNamespace):
    """
    Collection-level operations on a DocType.

    Thin controller delegating to the doctype service through ``run_frappe``. The page
    size is clamped server-side (analysis S1-3); fields/order_by/filters are sanitized by
    the underlying Frappe query layer.
    """

    _handler_map: ClassVar[dict[str, str]] = {}

    @FraxisNamespace.handler("doctype:list")
    async def on_doctype_list(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype")
            doctype = data["doctype"]
            limit = clamp_limit(data.get("limit"))
            await self._emit_state(sid, "doctype", "list", "start")

            result = await run_frappe(
                doctype_service.list_documents,
                doctype,
                data.get("filters"),
                data.get("fields"),
                limit,
                int(data.get("limit_start", 0) or 0),
                data.get("order_by"),
                user=user,
            )
            response = Response.success(data=result, metadata=metadata)
            await self._emit_state(sid, "doctype", "list", "success", response.to_dict())
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "list", "DOCTYPE_LIST_FAILED", e, data, metadata)

    @FraxisNamespace.handler("doctype:count")
    async def on_doctype_count(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype")
            await self._emit_state(sid, "doctype", "count", "start")
            count = await run_frappe(
                doctype_service.count_documents, data["doctype"], data.get("filters"), user=user
            )
            response = Response.success(data={"count": count}, metadata=metadata)
            await self._emit_state(sid, "doctype", "count", "success", response.to_dict())
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "count", "DOCTYPE_COUNT_FAILED", e, data, metadata)

    @FraxisNamespace.handler("doctype:meta")
    async def on_doctype_meta(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype")
            await self._emit_state(sid, "doctype", "meta", "start")
            meta = await run_frappe(
                doctype_service.get_doctype_meta, data["doctype"], user=user
            )
            response = Response.success(data=meta, metadata=metadata)
            await self._emit_state(sid, "doctype", "meta", "success", response.to_dict())
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "meta", "DOCTYPE_META_FAILED", e, data, metadata)

    @FraxisNamespace.handler("doctype:subscribe")
    async def on_doctype_subscribe(self, sid, data: dict = None) -> dict:
        """Subscribe to collection-level change events for a DocType.

        Permission is checked here at subscribe time and re-checked per recipient at
        broadcast time (``emit_to_permitted`` in ``DocumentNamespace``), so a user whose
        read access is revoked after subscribing stops receiving change events on the
        next broadcast without needing to reconnect (analysis S3-3, §7.5).

        An optional ``filter`` narrows delivery to documents whose data matches the
        clauses (e.g. ``payload.client_correlation_id == <uuid>`` for the widget). The
        subscription also bumps the registry refcount so the doc-event bridge activates
        for this doctype (fraxis_improvements_plan.md §A.2/§A.5).
        """
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype")
            doctype = data["doctype"]
            clauses = normalize_filter(data.get("filter"))
            await run_frappe(doctype_service.assert_read_permission, doctype, user=user)
            room = collection_room(doctype)
            await self.enter_room(sid, room)
            await self._track_subscription(
                sid, h=sub_registry.H_DT, key=doctype, room=room, filter_clauses=clauses
            )
            return Response.success(
                data={"subscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "subscribe", "DOCTYPE_SUBSCRIBE_FAILED", e, data, metadata, emit=False)

    @FraxisNamespace.handler("doctype:unsubscribe")
    async def on_doctype_unsubscribe(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            await self.require_user(sid)
            require(data, "doctype")
            room = collection_room(data["doctype"])
            await self.leave_room(sid, room)
            await self._untrack_subscription(sid, room)
            return Response.success(
                data={"unsubscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "unsubscribe", "DOCTYPE_UNSUBSCRIBE_FAILED", e, data, metadata, emit=False)

    async def _fail(self, sid, action, code, exc, data, metadata, emit=True):
        # File-based logger (not frappe.log_error) on purpose: this runs on the event
        # loop, where a DB insert+commit would block it and reuse the shared boot
        # connection (analysis S1-1/S2-1, §6). Traceback kept server-side via exc_info.
        frappe.logger("fraxis.doctype").error(
            f"doctype:{action} failed for {data.get('doctype')}: {exc}", exc_info=True
        )
        response = Response.failure(
            error=sanitize_error(exc),
            error_code=code,
            details={"doctype": data.get("doctype")},
            metadata=metadata,
        )
        if emit:
            await self._emit_state(sid, "doctype", action, "failure", response.to_dict())
        return response.to_dict()
