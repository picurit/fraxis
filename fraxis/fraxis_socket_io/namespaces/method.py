# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
import traceback
import asyncio
import inspect
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


class MethodNamespace(FraxisNamespace):
    """
    Handle execution of whitelisted Frappe methods and controller methods.
    
    Provides:
    - Synchronous/asynchronous execution via method:execute
    - Background job enqueueing via method:enqueue
    - Progress streaming for enqueued jobs (via AsyncRedisManager)
    - Server script execution
    """
    
    _handler_map: ClassVar[dict[str, str]] = {}

    def _get_whitelisted_method(self, method_name: str):
        """
        Resolve and validate a whitelisted method.
        
        Method resolution order:
        1. Check frappe.get_hooks('override_whitelisted_methods')
        2. Check server script map
        3. frappe.get_attr(method)
        4. frappe.is_whitelisted(method_fn) — raises if not whitelisted
        """
        # Check hooks for overrides
        overrides = frappe.get_hooks('override_whitelisted_methods') or {}
        if method_name in overrides:
            method = frappe.get_attr(overrides[method_name])
        else:
            # Get method via frappe.get_attr
            method = frappe.get_attr(method_name)
        
        # Validate method is whitelisted
        # Note: frappe.is_whitelisted() raises PermissionError if not whitelisted
        try:
            frappe.is_whitelisted(method)
        except frappe.PermissionError:
            raise frappe.PermissionError(f"Method {method_name} is not whitelisted")
        
        return method

    @FraxisNamespace.handler('method:execute')
    async def on_method_execute(self, sid, data: dict = None) -> dict:
        """
        Execute a whitelisted method synchronously or asynchronously.
        data: { method: str, args?: dict }
        Resolves method, validates is_whitelisted(), calls it.
        For async methods that declare a 'progress' parameter, injects a progress callback.
        Emits: method:execute:start → [method:execute:progress]* → method:execute:success/failure
        Returns: Response<Any>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            method_name = data.get('method')
            args = data.get('args', {})
            
            if not method_name:
                raise ValueError("method field is required")
            
            if not isinstance(args, dict):
                raise TypeError("args must be a dictionary")
            
            # Emit start state
            await self._emit_state(sid, 'method', 'execute', 'start')
            
            # Resolve and validate method
            method_func = self._get_whitelisted_method(method_name)
            
            # Define progress callback that will be injected if method accepts it
            # This callback captures 'sid' and 'method_name' via closure
            async def _progress(percent, title=None, description=None, data=None):
                """
                Progress callback for async methods.
                Emits progress events to the requesting client and method subscribers.
                """
                payload = {
                    'percent': percent,
                    'title': title,
                    'description': description,
                    'data': data  # arbitrary structured payload
                }
                
                # Emit to requesting client (private room via sid)
                await self._emit_state(sid, 'method', 'execute', 'progress', payload)
                
                # Broadcast to method subscribers
                await self.emit('method:execute:progress', {
                    'method': method_name,
                    **payload
                }, room=f"method:{method_name}")
            
            # Check if method signature includes 'progress' parameter
            # If so, inject the callback
            sig = inspect.signature(method_func)
            call_args = args.copy()
            
            if 'progress' in sig.parameters:
                call_args['progress'] = _progress
            
            # Execute method inside a dedicated thread so that each concurrent
            # invocation gets its own frappe.local (and thus its own frappe.db
            # connection). Running two async coroutines that share the single
            # frappe.db opened at server startup causes MySQL packet-sequence
            # errors when they interleave their DB calls on the same socket.
            #
            # Each worker thread calls frappe.init() + frappe.connect() to
            # set up a fully isolated Frappe context (local.site, local.flags,
            # local.db, etc.), then frappe.destroy() in the finally block.
            # Async methods are run on a dedicated event loop inside the thread
            # so they never contend with the main loop or other threads.
            # The progress callback is bridged back to the main loop via
            # asyncio.run_coroutine_threadsafe().

            loop = asyncio.get_event_loop()

            # Capture site name from the main thread's frappe context so the
            # worker thread can initialise its own frappe.local correctly.
            _site = frappe.local.site
            _sites_path = getattr(frappe.local, 'sites_path', '.')

            def _make_progress_threadsafe(progress_coro_fn):
                """
                Return an async wrapper that can be awaited from within the
                thread's own event loop.  It schedules the actual Socket.IO
                emit (progress_coro_fn) onto the *main* event loop via
                run_coroutine_threadsafe, then waits for it to finish using
                asyncio.wrap_future (which attaches to the current thread loop).
                """
                async def _threadsafe_progress(percent, title=None, description=None, data=None):
                    future = asyncio.run_coroutine_threadsafe(
                        progress_coro_fn(percent, title=title, description=description, data=data),
                        loop
                    )
                    # Await the concurrent.futures.Future on the thread's own loop.
                    await asyncio.wrap_future(future)

                return _threadsafe_progress

            async def _run_in_thread():
                """
                Execute method_func inside a worker thread with an isolated
                frappe DB connection, then return the result to the caller.
                """
                # Replace the async progress callback with a thread-safe variant.
                threadsafe_call_args = call_args.copy()
                if 'progress' in threadsafe_call_args:
                    threadsafe_call_args['progress'] = _make_progress_threadsafe(_progress)

                def _thread_body():
                    # Each thread has its own frappe.local (werkzeug threading.local).
                    # We must call frappe.init() + frappe.connect() here to set up
                    # local.site, local.flags, local.db etc. for this thread.
                    frappe.init(site=_site, sites_path=_sites_path)
                    frappe.connect()

                    try:
                        raw_result = method_func(**threadsafe_call_args)

                        # method_func may return a coroutine (async def wrapped by
                        # @frappe.whitelist).  Run it on a *new* event loop inside
                        # this thread so it does not compete with the main loop.
                        if asyncio.iscoroutine(raw_result):
                            thread_loop = asyncio.new_event_loop()
                            try:
                                raw_result = thread_loop.run_until_complete(raw_result)
                            finally:
                                thread_loop.close()

                        elif inspect.isasyncgen(raw_result):
                            thread_loop = asyncio.new_event_loop()
                            collected_values = []
                            value_count = 0

                            async def _consume_gen():
                                nonlocal value_count
                                async for value in raw_result:
                                    value_count += 1
                                    collected_values.append(value)
                                    if threadsafe_call_args.get('progress'):
                                        await threadsafe_call_args['progress'](
                                            percent=None,
                                            title="AsyncIterator Progress",
                                            description=f"Received value {value_count}",
                                            data={'value': value, 'index': value_count - 1}
                                        )

                            try:
                                thread_loop.run_until_complete(_consume_gen())
                            finally:
                                thread_loop.close()

                            raw_result = {
                                'values': collected_values,
                                'total_count': value_count,
                                'async_iterator': True
                            }

                        frappe.db.commit()
                        return raw_result

                    finally:
                        frappe.destroy()

                # Run the thread body in the default executor (ThreadPoolExecutor).
                return await loop.run_in_executor(None, _thread_body)

            result = await _run_in_thread()
            
            # Build response
            response = Response.success(
                data=result,
                metadata=metadata
            )
            
            # Emit success state
            await self._emit_state(sid, 'method', 'execute', 'success', response.to_dict())
            
            # Broadcast to method subscription room
            await self.emit('method:execute:success', response.to_dict(), room=f"method:{method_name}")
            
            # DB commit and close are handled inside _thread_body.
            # No commit needed here on the main event-loop thread.
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='METHOD_EXECUTE_FAILED',
                details={'method': data.get('method')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'method', 'execute', 'failure', response.to_dict())
            
            # Broadcast to method subscription room
            await self.emit('method:execute:failure', response.to_dict(), room=f"method:{data.get('method')}")
            
            return response.to_dict()

    @FraxisNamespace.handler('method:enqueue')
    async def on_method_enqueue(self, sid, data: dict = None) -> dict:
        """
        Enqueue a whitelisted method as a background job.
        data: { method: str, args?: dict }
        Enqueues as background job via frappe.enqueue().
        Adds client to both method:<method_name> (method-level) and method:<method_name>:<task_id> (job-specific) rooms.
        Emits: method:enqueue:start { task_id } to sid
        Broadcasts: method:enqueue:start to method:<method_name> room
        Returns: Response<{ task_id: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            method_name = data.get('method')
            args = data.get('args', {})
            
            if not method_name:
                raise ValueError("method field is required")
            
            if not isinstance(args, dict):
                raise TypeError("args must be a dictionary")
            
            # Emit start state (before enqueueing)
            await self._emit_state(sid, 'method', 'enqueue', 'start')
            
            # Validate method is whitelisted
            self._get_whitelisted_method(method_name)
            
            # Enqueue the job
            job = frappe.enqueue(method_name, **args)
            task_id = job.id
            
            # Add client to subscription rooms
            method_room = f"method:{method_name}"
            task_room = f"method:{method_name}:{task_id}"
            
            await self.enter_room(sid, method_room)
            await self.enter_room(sid, task_room)
            
            # Build response
            response_data = {'task_id': task_id}
            response = Response.success(
                data=response_data,
                metadata=metadata
            )
            
            # Emit success state with task_id
            await self._emit_state(sid, 'method', 'enqueue', 'success', {
                **response.to_dict(),
                'data': response_data
            })
            
            # Broadcast method-level notification
            await self.emit('method:enqueue:start', {
                'task_id': task_id,
                'method': method_name
            }, room=method_room)
            
            frappe.db.commit()
            return response.to_dict()
            
        except Exception as e:
            response = Response.failure(
                error=str(e),
                error_code='METHOD_ENQUEUE_FAILED',
                details={'method': data.get('method')},
                stack_trace=traceback.format_exc(),
                metadata=metadata
            )
            
            # Emit failure state
            await self._emit_state(sid, 'method', 'enqueue', 'failure', response.to_dict())
            
            return response.to_dict()

    @FraxisNamespace.handler('method:subscribe')
    async def on_method_subscribe(self, sid, data: dict = None) -> dict:
        """
        Subscribe to all lifecycle events for a specific whitelisted method.
        data: { method: str }
        Validates method is whitelisted via is_whitelisted(method).
        Adds client to method:<method_name> room.
        Returns: Response<{ subscribed: True, room: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            method_name = data.get('method')
            
            if not method_name:
                raise ValueError("method field is required")
            
            # Validate method is whitelisted
            self._get_whitelisted_method(method_name)
            
            room = f"method:{method_name}"
            
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
                error_code='METHOD_SUBSCRIBE_FAILED',
                details={'method': data.get('method')},
                metadata=metadata
            )
            
            return response.to_dict()

    @FraxisNamespace.handler('method:unsubscribe')
    async def on_method_unsubscribe(self, sid, data: dict = None) -> dict:
        """
        Unsubscribe from lifecycle events for a specific method.
        data: { method: str }
        Removes client from method:<method_name> room.
        Returns: Response<{ unsubscribed: True, room: str }>  (ACK)
        """
        metadata = _get_metadata(sid)
        
        # Ensure data is a dict, not None
        if data is None:
            data = {}

        try:
            method_name = data.get('method')
            
            if not method_name:
                raise ValueError("method field is required")
            
            room = f"method:{method_name}"
            
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
                error_code='METHOD_UNSUBSCRIBE_FAILED',
                details={'method': data.get('method')},
                metadata=metadata
            )
            
            return response.to_dict()
