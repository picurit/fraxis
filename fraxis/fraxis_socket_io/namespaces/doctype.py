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
        from frappe.utils import now as frappe_now
        timestamp = frappe_now()
        site = frappe.local.site if hasattr(frappe, 'local') else 'Unknown'
    except:
        timestamp = datetime.now().isoformat()
        site = 'Unknown'
    
    return {
        'timestamp': timestamp,
        'sid': sid,
        'site': site
    }


class DoctypeNamespace(FraxisNamespace):
    """
    Handle collection-level operations on a DocType.
    
    Provides:
    - Paginated list queries with filters and field selection
    - Document count queries
    - DocType metadata retrieval
    - Subscribe/unsubscribe to DocType-level creation events
    """
    
    _handler_map: ClassVar[dict[str, str]] = {}

    @FraxisNamespace.handler('doctype:list')
    async def on_doctype_list(self, sid, data: dict) -> dict:
        """
        Query a paginated list of documents.
        data: { doctype, filters?, fields?, limit?, limit_start?, order_by? }
        Wraps frappe.client.get_list()
        Emits: doctype:list:start → doctype:list:success/failure
        Returns: Response<Doc[]>
        """
        metadata = _get_metadata(sid)
        
        try:
            doctype = data.get('doctype')
            filters = data.get('filters', None)
            fields = data.get('fields', None)
            limit = data.get('limit', 20)
            limit_start = data.get('limit_start', 0)
            order_by = data.get('order_by', None)
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            # Emit start state
            await self._emit_state(sid, 'doctype', 'list', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype}")
            
            # Build query parameters
            query_params = {
                'filters': filters,
                'fields': fields,
                'limit_page_length': limit,
                'limit_page_length_count': limit,
                'offset': limit_start,
            }
            
            if order_by:
                query_params['order_by'] = order_by
            
            # Execute list query
            result = frappe.client.get_list(doctype, **query_params)
            
            # Build response
            response = Response.success(
                data=result,
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'doctype', 'list', 'success', response.to_dict())
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCTYPE_LIST_FAILED',
                details={'doctype': data.get('doctype')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'doctype', 'list', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('doctype:count')
    async def on_doctype_count(self, sid, data: dict) -> dict:
        """
        Count documents matching filters.
        data: { doctype, filters? }
        Wraps frappe.db.count()
        Emits: doctype:count:start → doctype:count:success/failure
        Returns: Response<{ count: int }>
        """
        metadata = _get_metadata(sid)
        
        try:
            doctype = data.get('doctype')
            filters = data.get('filters', None)
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            # Emit start state
            await self._emit_state(sid, 'doctype', 'count', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype}")
            
            # Execute count query
            count = frappe.db.count(doctype, filters=filters)
            
            # Build response
            response = Response.success(
                data={'count': count},
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'doctype', 'count', 'success', response.to_dict())
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCTYPE_COUNT_FAILED',
                details={'doctype': data.get('doctype')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'doctype', 'count', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('doctype:meta')
    async def on_doctype_meta(self, sid, data: dict) -> dict:
        """
        Retrieve DocType metadata (field definitions, permissions, etc).
        data: { doctype }
        Wraps frappe.get_meta()
        Emits: doctype:meta:start → doctype:meta:success/failure
        Returns: Response<Meta>
        """
        metadata = _get_metadata(sid)
        
        try:
            doctype = data.get('doctype')
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            # Emit start state
            await self._emit_state(sid, 'doctype', 'meta', 'start')
            
            # Check permissions
            if not frappe.has_permission(doctype, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype}")
            
            # Get meta
            meta = frappe.get_meta(doctype)
            meta_dict = meta.as_dict()
            
            # Build response
            response = Response.success(
                data=meta_dict,
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'doctype', 'meta', 'success', response.to_dict())
            
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='DOCTYPE_META_FAILED',
                details={'doctype': data.get('doctype')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'doctype', 'meta', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('doctype:subscribe')
    async def on_doctype_subscribe(self, sid, data: dict) -> dict:
        """
        Subscribe to new-document notifications for a specific DocType.
        data: { doctype }
        Returns: Response<{ subscribed: True, room: str }>
        """
        metadata = _get_metadata(sid)
        
        try:
            doctype = data.get('doctype')
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            # Check permissions
            if not frappe.has_permission(doctype, ptype='read'):
                raise frappe.PermissionError(f"You do not have read permission on {doctype}")
            
            room = f"doctype:{doctype}"
            
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
                error_code='DOCTYPE_SUBSCRIBE_FAILED',
                details={'doctype': data.get('doctype')},
                metadata=metadata
            )
            
            return response.to_dict()

    @FraxisNamespace.handler('doctype:unsubscribe')
    async def on_doctype_unsubscribe(self, sid, data: dict) -> dict:
        """
        Unsubscribe from new-document notifications for a specific DocType.
        data: { doctype }
        Returns: Response<{ unsubscribed: True, room: str }>
        """
        metadata = _get_metadata(sid)
        
        try:
            doctype = data.get('doctype')
            
            if not doctype:
                raise ValueError("doctype field is required")
            
            room = f"doctype:{doctype}"
            
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
                error_code='DOCTYPE_UNSUBSCRIBE_FAILED',
                details={'doctype': data.get('doctype')},
                metadata=metadata
            )
            
            return response.to_dict()
