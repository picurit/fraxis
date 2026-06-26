# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
from typing import ClassVar

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.fraxis_socket_io.context import build_metadata
from fraxis.runtime.frappe_executor import run_frappe
from fraxis.services import document as document_service
from fraxis.services.validation import collection_room, document_room, require, sanitize_error
from fraxis.utils.cornerstone.response import Response


class DocumentNamespace(FraxisNamespace):
    """
    Full CRUD on individual Frappe documents.

    Thin controller: it authenticates the sid, deserializes the request, delegates the
    unit of work to a service through ``run_frappe`` (own connection / transaction /
    identity), serializes the envelope, and broadcasts a coherent change signal.

    Broadcast contract:
    - per-document room ``document:{doctype}:{name}`` receives ``document:updated`` /
      ``document:deleted`` (document:subscribe joins it, in this namespace);
    - collection room ``doctype:{doctype}`` (joined by doctype:subscribe in /api/doctype)
      receives ``document:created`` and a uniform ``document:changed`` for every action —
      emitted with an explicit ``namespace`` so it crosses namespaces correctly (S3-2).
    """

    _handler_map: ClassVar[dict[str, str]] = {}
    DOCTYPE_NAMESPACE = "/api/doctype"

    async def _broadcast_change(self, doctype, name, action, per_document=False):
        """Emit the collection-level change signal (and per-document for update/delete).

        Recipients are filtered by a fresh read-permission check at emit time
        (``emit_to_permitted``), so a user whose access was revoked after subscribing
        stops receiving change events on the next broadcast (analysis S3-3, §7.5).
        """
        await self.emit_to_permitted(
            "document:changed",
            {"doctype": doctype, "name": name, "action": action},
            doctype=doctype,
            room=collection_room(doctype),
            namespace=self.DOCTYPE_NAMESPACE,
        )
        if per_document:
            await self.emit_to_permitted(
                f"document:{action}d" if action != "create" else "document:created",
                {"doctype": doctype, "name": name},
                doctype=doctype,
                room=document_room(doctype, name),
                namespace=self.namespace,
            )

    @FraxisNamespace.handler("document:create")
    async def on_document_create(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype")
            doctype = data.get("doctype")
            await self._emit_state(sid, "document", "create", "start")

            doc = await run_frappe(
                document_service.create_document, doctype, data.get("data", {}), user=user
            )
            response = Response.success(data=doc, metadata=metadata)
            await self._emit_state(sid, "document", "create", "success", response.to_dict())

            await self.emit_to_permitted(
                "document:created",
                {"doctype": doctype, "name": doc.get("name")},
                doctype=doctype,
                room=collection_room(doctype),
                namespace=self.DOCTYPE_NAMESPACE,
            )
            await self.emit_to_permitted(
                "document:changed",
                {"doctype": doctype, "name": doc.get("name"), "action": "create"},
                doctype=doctype,
                room=collection_room(doctype),
                namespace=self.DOCTYPE_NAMESPACE,
            )
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "create", "DOCUMENT_CREATE_FAILED", e, data, metadata)

    @FraxisNamespace.handler("document:read")
    async def on_document_read(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype", "name")
            await self._emit_state(sid, "document", "read", "start")
            doc = await run_frappe(
                document_service.read_document, data["doctype"], data["name"], user=user
            )
            response = Response.success(data=doc, metadata=metadata)
            await self._emit_state(sid, "document", "read", "success", response.to_dict())
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "read", "DOCUMENT_READ_FAILED", e, data, metadata)

    @FraxisNamespace.handler("document:update")
    async def on_document_update(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype", "name")
            doctype, name = data["doctype"], data["name"]
            await self._emit_state(sid, "document", "update", "start")

            doc = await run_frappe(
                document_service.update_document, doctype, name, data.get("data", {}), user=user
            )
            response = Response.success(data=doc, metadata=metadata)
            await self._emit_state(sid, "document", "update", "success", response.to_dict())
            await self._broadcast_change(doctype, name, "update", per_document=True)
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "update", "DOCUMENT_UPDATE_FAILED", e, data, metadata)

    @FraxisNamespace.handler("document:delete")
    async def on_document_delete(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype", "name")
            doctype, name = data["doctype"], data["name"]
            await self._emit_state(sid, "document", "delete", "start")

            result = await run_frappe(
                document_service.delete_document, doctype, name, user=user
            )
            response = Response.success(data=result, metadata=metadata)
            await self._emit_state(sid, "document", "delete", "success", response.to_dict())
            await self._broadcast_change(doctype, name, "delete", per_document=True)
            return response.to_dict()
        except Exception as e:
            return await self._fail(sid, "delete", "DOCUMENT_DELETE_FAILED", e, data, metadata)

    @FraxisNamespace.handler("document:subscribe")
    async def on_document_subscribe(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            user = await self.require_user(sid)
            require(data, "doctype", "name")
            doctype, name = data["doctype"], data["name"]
            await run_frappe(
                document_service.assert_read_permission, doctype, name, user=user
            )
            room = document_room(doctype, name)
            await self.enter_room(sid, room)
            return Response.success(
                data={"subscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "subscribe", "DOCUMENT_SUBSCRIBE_FAILED", e, data, metadata, emit=False)

    @FraxisNamespace.handler("document:unsubscribe")
    async def on_document_unsubscribe(self, sid, data: dict = None) -> dict:
        metadata = build_metadata(sid)
        data = data or {}
        try:
            await self.require_user(sid)
            require(data, "doctype", "name")
            room = document_room(data["doctype"], data["name"])
            await self.leave_room(sid, room)
            return Response.success(
                data={"unsubscribed": True, "room": room}, metadata=metadata
            ).to_dict()
        except Exception as e:
            return await self._fail(sid, "unsubscribe", "DOCUMENT_UNSUBSCRIBE_FAILED", e, data, metadata, emit=False)

    async def _fail(self, sid, action, code, exc, data, metadata, emit=True):
        """Log server-side, return a sanitized failure envelope (no traceback to client).

        Logging uses ``frappe.logger`` (file-based, non-blocking) rather than
        ``frappe.log_error`` deliberately: this runs on the event-loop thread, and
        ``frappe.log_error`` would issue a synchronous DB insert+commit on the shared
        boot connection — blocking the loop and reintroducing the cross-handler
        transaction interleaving the refactor removes (analysis S1-1, S2-1, §6). The
        full traceback is captured server-side via ``exc_info`` (analysis S2-2 / P7).
        """
        frappe.logger("fraxis.document").error(
            f"document:{action} failed for {data.get('doctype')}: {exc}", exc_info=True
        )
        response = Response.failure(
            error=sanitize_error(exc),
            error_code=code,
            details={"doctype": data.get("doctype"), "name": data.get("name")},
            metadata=metadata,
        )
        if emit:
            await self._emit_state(sid, "document", action, "failure", response.to_dict())
        return response.to_dict()
