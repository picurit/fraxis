# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Frappe RQ job hooks for emitting success/failure events to Fraxis Socket.IO clients.

These hooks are called by Frappe's execute_job() after every background job completes.
They use AsyncRedisManager in write-only mode to emit method:enqueue:success/failure
events directly to Socket.IO rooms.
"""

import frappe
from socketio import AsyncRedisManager
import asyncio


# Lazy-initialized write-only Redis manager
_redis_manager = None


def _get_redis_manager():
    """
    Get or create a write-only AsyncRedisManager for job completion events.
    
    Shared with fraxis.utils.realtime.publish_progress but separate instance
    to avoid coupling.
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
        # Must set server to None for write-only mode
        _redis_manager.server = None
    
    return _redis_manager


def after_job(method, **kwargs):
    """
    Frappe hook called after every RQ job completes (success or failure).
    
    Emits method:enqueue:success or method:enqueue:failure events to Socket.IO clients
    via AsyncRedisManager using Redis publish directly (no asyncio event loop needed).
    
    Args:
        method: Method name that was executed
        **kwargs: Additional job execution data, including:
            - result: Job return value (on success)
            - job_name: Job ID/task_id
    """
    import pickle
    from redis import Redis
    
    # Only emit for methods (not all background jobs)
    if not method:
        return
    
    # Get task_id from job_name
    task_id = kwargs.get('job_name')
    if not task_id:
        # Try to get from RQ context
        try:
            from rq import get_current_job
            job = get_current_job()
            if job:
                task_id = job.id
        except Exception:
            pass
    
    if not task_id:
        return
    
    # Determine success or failure based on presence of result
    result = kwargs.get('result')
    is_success = result is not None or 'result' in kwargs
    
    # Build event payload
    if is_success:
        event_name = 'method:enqueue:success'
        payload = {
            'task_id': task_id,
            'result': result
        }
    else:
        event_name = 'method:enqueue:failure'
        payload = {
            'task_id': task_id,
            'error': 'Job failed'
        }
    
    # Build Socket.IO pub/sub message format
    # This matches what AsyncRedisManager.emit() publishes
    job_room = f"method:{method}:{task_id}"
    method_room = f"method:{method}"
    
    # Create messages in AsyncPubSubManager format
    import uuid
    host_id = uuid.uuid4().hex
    
    job_message = {
        'method': 'emit',
        'event': event_name,
        'data': payload,
        'namespace': '/api/method',
        'room': job_room,
        'skip_sid': None,
        'callback': None,
        'host_id': host_id
    }
    
    method_message = {
        'method': 'emit',
        'event': event_name,
        'data': {'method': method, **payload},
        'namespace': '/api/method',
        'room': method_room,
        'skip_sid': None,
        'callback': None,
        'host_id': host_id
    }
    
    # Publish directly to Redis using synchronous Redis client
    try:
        redis_url = frappe.conf.redis_queue
        redis_client = Redis.from_url(redis_url)
        
        # Publish both messages to 'fraxis' channel
        # AsyncRedisManager uses pickle for serialization
        redis_client.publish('fraxis', pickle.dumps(job_message))
        redis_client.publish('fraxis', pickle.dumps(method_message))
        
        redis_client.close()
    except Exception as e:
        frappe.logger("job_hooks").error(f"Failed to publish job completion event: {str(e)}")
