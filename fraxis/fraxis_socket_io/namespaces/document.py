# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
import traceback
from typing import ClassVar
from datetime import datetime
from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.utils.cornerstone.response import Response


def _get_metadata(sid: str) -> dict:
    """Helper to safely get frappe metadata."""
    try:
        timestamp = frappe.utils.now()
        site = frappe.local.site if hasattr(frappe, 'local') else 'Unknown'
    except:
        timestamp = datetime.now().isoformat()
        site = 'Unknown'
    
    return {
        'timestamp': timestamp,
        'sid': sid,
        'site': site
    }


class DocumentNamespace(FraxisNamespace):
    """
    Handle full CRUD on individual Frappe documents.
    
    Provides:
    - Create, read, update, delete on any DocType the authenticated user has permission for
    - Subscribe/unsubscribe to real-time change notifications for specific documents
    - Broadcast change events to all subscribers when a document is saved or deleted
    """
    
    _handler_map: ClassVar[dict[str, str]] = {}

    @FraxisNamespace.handler('document:create')
    async def on_document_create(self, sid, data: dict = None) -> dict:
        """
        Create a new document.
        data: { doctype: str, data: dict }
        Emits: document:create:start → document:create:success/failure
        Broadcasts: document:created to doctype:<doctype> room
        Returns: Response<Doc>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        # Ensure data is a dict, not None
        if data is None:
            data = {}
        
        try:
            doctype = data.get('doctype')
            doc_data = data.get('data', {})
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            # Emit start state
            await self._emit_state(sid, 'document', 'create', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, ptype='write'):
                raise frappe.PermissionError(f"You do not have write permission on {doctype}")
            
            # Create and insert document
            doc = frappe.new_doc(doctype)
            doc.update(doc_data)
            doc.insert()
            frappe.db.commit()
            
            # Build response
            response = Response.success(
                data=doc.as_dict(),
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'document', 'create', 'success', response.to_dict())
            
            # Broadcast to doctype room
            await self.emit('document:created', {
                'doctype': doctype,
                'name': doc.name
            }, room=f"doctype:{doctype}")
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_CREATE_FAILED',
                details={'doctype': data.get('doctype')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'document', 'create', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('document:read')
    async def on_document_read(self, sid, data: dict = None) -> dict:
        """
        Read a document by name.
        data: { doctype: str, name: str }
        Emits: document:read:start → document:read:success/failure
        Returns: Response<Doc>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        # Ensure data is a dict, not None
        if data is None:
            data = {}
        
        try:
            doctype = data.get('doctype')
            name = data.get('name')
            
            if not doctype or not name:
                raise ValueError("doctype and name fields are required")
            
            # Emit start state
            await self._emit_state(sid, 'document', 'read', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, doc=name, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype} {name}")
            
            # Fetch document
            doc = frappe.get_doc(doctype, name)
            
            # Build response
            response = Response.success(
                data=doc.as_dict(),
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'document', 'read', 'success', response.to_dict())
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_READ_FAILED',
                details={'doctype': data.get('doctype'), 'name': data.get('name')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'document', 'read', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('document:update')
    async def on_document_update(self, sid, data: dict = None) -> dict:
        """
        Update fields on an existing document.
        data: { doctype: str, name: str, data: dict }
        Emits: document:update:start → document:update:success/failure
        Broadcasts: document:updated to document:<doctype>/<name> room
        Returns: Response<Doc>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            doctype = data.get('doctype')
            name = data.get('name')
            doc_data = data.get('data', {})
            
            if not doctype or not name:
                raise ValueError("doctype and name fields are required")
            
            # Emit start state
            await self._emit_state(sid, 'document', 'update', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, doc=name, ptype='write'):
                raise frappe.PermissionError(f"You do not have write permission on {doctype} {name}")
            
            # Fetch, update, and save document
            doc = frappe.get_doc(doctype, name)
            doc.update(doc_data)
            doc.save()
            frappe.db.commit()
            
            # Build response
            response = Response.success(
                data=doc.as_dict(),
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'document', 'update', 'success', response.to_dict())
            
            # Broadcast to document room
            await self.emit('document:updated', {
                'doctype': doctype,
                'name': name
            }, room=f"document:{doctype}:{name}")
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_UPDATE_FAILED',
                details={'doctype': data.get('doctype'), 'name': data.get('name')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'document', 'update', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('document:delete')
    async def on_document_delete(self, sid, data: dict = None) -> dict:
        """
        Delete a document.
        data: { doctype: str, name: str }
        Emits: document:delete:start → document:delete:success/failure
        Broadcasts: document:deleted to document:<doctype>/<name> room
        Returns: Response<{ name: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            doctype = data.get('doctype')
            name = data.get('name')
            
            if not doctype or not name:
                raise ValueError("doctype and name fields are required")
            
            # Emit start state
            await self._emit_state(sid, 'document', 'delete', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, doc=name, ptype='delete'):
                raise frappe.PermissionError(f"You do not have delete permission on {doctype} {name}")
            
            # Delete document
            frappe.delete_doc(doctype, name)
            frappe.db.commit()
            
            # Build response
            response = Response.success(
                data={'name': name},
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'document', 'delete', 'success', response.to_dict())
            
            # Broadcast to document room
            await self.emit('document:deleted', {
                'doctype': doctype,
                'name': name
            }, room=f"document:{doctype}:{name}")
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_DELETE_FAILED',
                details={'doctype': data.get('doctype'), 'name': data.get('name')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'document', 'delete', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('document:subscribe')
    async def on_document_subscribe(self, sid, data: dict = None) -> dict:
        """
        Subscribe to change notifications for a specific document.
        data: { doctype: str, name: str }
        Validates read permission, then enters room.
        Returns: Response<{ subscribed: True, room: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            doctype = data.get('doctype')
            name = data.get('name')
            
            if not doctype or not name:
                raise ValueError("doctype and name fields are required")
            
            # Check permissions
            if not frappe.has_permission(doctype, doc=name, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype} {name}")
            
            room = f"document:{doctype}:{name}"
            
            # Enter subscription room
            await self.enter_room(sid, room)
            
            response = Response.success(
                data={'subscribed': True, 'room': room},
                metadata=metadata
            )
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_SUBSCRIBE_FAILED',
                details={'doctype': data.get('doctype'), 'name': data.get('name')},
                metadata=metadata
            )
            
            return response.to_dict()

    @FraxisNamespace.handler('document:unsubscribe')
    async def on_document_unsubscribe(self, sid, data: dict = None) -> dict:
        """
        Unsubscribe from change notifications for a specific document.
        data: { doctype: str, name: str }
        Returns: Response<{ unsubscribed: True, room: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            doctype = data.get('doctype')
            name = data.get('name')
            
            if not doctype or not name:
                raise ValueError("doctype and name fields are required")
            
            room = f"document:{doctype}:{name}"
            
            # Leave subscription room
            await self.leave_room(sid, room)
            
            response = Response.success(
                data={'unsubscribed': True, 'room': room},
                metadata=metadata
            )
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCUMENT_UNSUBSCRIBE_FAILED',
                details={'doctype': data.get('doctype'), 'name': data.get('name')},
                metadata=metadata
            )
            
            return response.to_dict()
