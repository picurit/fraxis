# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Fraxis realtime utilities for progress publishing from RQ workers.

This module provides direct Socket.IO event emission from RQ worker processes
using AsyncRedisManager in write-only mode, enabling progress updates with
arbitrary structured payloads.
"""

import frappe
from socketio import AsyncRedisManager


# Lazy-initialized write-only Redis manager for RQ workers
_redis_manager = None


def _get_redis_manager():
    """
    Get or create a write-only AsyncRedisManager for publishing from RQ workers.
    
    This manager is initialized lazily and cached for the lifetime of the worker process.
    It uses the same 'fraxis' channel as the main Socket.IO server.
    """
    global _redis_manager
    
    if _redis_manager is None:
        redis_url = frappe.conf.redis_queue
        _redis_manager = AsyncRedisManager(
            url=redis_url,
            channel='fraxis',      # Same channel as Fraxis Socket.IO server
            write_only=True,       # RQ workers only publish, never receive
            logger=False
        )
        # Must set server to None for write-only mode to work properly
        _redis_manager.server = None
    
    return _redis_manager


def publish_progress(percent, title=None, description=None, data=None, task_id=None, method_name=None):
    """
    Publish progress updates from RQ workers directly to Fraxis Socket.IO clients.
    
    Publishes directly to Redis 'fraxis' channel using synchronous Redis client,
    bypassing asyncio to avoid event loop issues in RQ workers.
    
    Args:
        percent (float): Progress percentage (0-100)
        title (str, optional): Progress title/heading
        description (str, optional): Progress description/status message
        data (Any, optional): Arbitrary structured payload (dict, list, etc.)
                             Enables streaming partial results, intermediate data, etc.
        task_id (str, optional): RQ task ID. Auto-detected from frappe.local.task_id if not provided.
        method_name (str, optional): Method name. Auto-detected from frappe.local.method_name if not provided.
    
    Usage inside an enqueued method:
        @frappe.whitelist()
        def generate_report(year):
            # Method name is auto-detected from RQ job context
            for i, month in enumerate(months):
                data = compute_month_data(year, month)
                
                fraxis.utils.realtime.publish_progress(
                    percent=round((i+1)/12*100, 1),
                    title="Generating Report",
                    description=f"Processed {month}",
                    data={"month": month, "rows": data}  # arbitrary payload
                )
            
            return {"status": "complete", "year": year}
    
    Event Flow:
        RQ Worker → publish_progress() → Redis 'fraxis' channel
        → Fraxis Socket.IO Server (AsyncRedisManager)
        → Socket.IO Clients in rooms: method:{method_name}:{task_id} and method:{method_name}
    
    Note:
        - Falls back to standard frappe.publish_progress() if no task context available
        - Requires both task_id and method_name (auto-detected from RQ job)
        - Emits directly to Fraxis event taxonomy - no translation needed
    """
    import pickle
    import uuid
    from redis import Redis
    
    # Auto-detect task_id from context if not provided
    if task_id is None:
        # Try frappe.local.task_id first (set by execute_job)
        if hasattr(frappe.local, "task_id") and frappe.local.task_id:
            task_id = frappe.local.task_id
        else:
            # Try to get from RQ context
            try:
                from rq import get_current_job
                job = get_current_job()
                if job:
                    task_id = job.id
            except Exception:
                pass
    
    # Auto-detect method_name from context if not provided
    if method_name is None:
        # Try frappe.local.job.method first
        if hasattr(frappe.local, "job") and hasattr(frappe.local.job, "method"):
            method_name = frappe.local.job.method
        else:
            # Try to get from RQ context
            try:
                from rq import get_current_job
                job = get_current_job()
                if job and hasattr(job, 'func_name'):
                    method_name = job.func_name
            except Exception:
                pass
    
    # Fallback if we don't have both task_id and method_name
    if task_id is None or method_name is None:
        # No task context — fall back to standard frappe progress
        frappe.publish_progress(percent, title=title, description=description)
        return
    
    # Build progress payload using Fraxis event taxonomy
    progress_payload = {
        'task_id': task_id,
        'percent': percent,
        'title': title,
        'description': description,
        'data': data  # arbitrary payload
    }
    
    # Build Socket.IO pub/sub messages in AsyncPubSubManager format
    # This matches what AsyncRedisManager.emit() publishes
    job_room = f"method:{method_name}:{task_id}"
    method_room = f"method:{method_name}"
    host_id = uuid.uuid4().hex
    
    job_message = {
        'method': 'emit',
        'event': 'method:enqueue:progress',
        'data': progress_payload,
        'namespace': '/api/method',
        'room': job_room,
        'skip_sid': None,
        'callback': None,
        'host_id': host_id
    }
    
    method_message = {
        'method': 'emit',
        'event': 'method:enqueue:progress',
        'data': {'method': method_name, **progress_payload},
        'namespace': '/api/method',
        'room': method_room,
        'skip_sid': None,
        'callback': None,
        'host_id': host_id
    }
    
    # Publish directly to Redis using synchronous client
    try:
        redis_url = frappe.conf.redis_queue
        redis_client = Redis.from_url(redis_url)
        
        # Publish both messages to 'fraxis' channel
        # AsyncRedisManager uses pickle for serialization
        redis_client.publish('fraxis', pickle.dumps(job_message))
        redis_client.publish('fraxis', pickle.dumps(method_message))
        
        redis_client.close()
    except Exception as e:
        frappe.logger("realtime").error(f"Failed to publish progress event: {str(e)}")
    
    # For compatibility: also publish to Frappe's standard channel
    # This allows Frappe desk to still monitor progress
    frappe.publish_progress(percent, title=title, description=description)
