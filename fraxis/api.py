# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import frappe
import asyncio
import random
import time
from typing import Optional, List, AsyncIterator


# ============================================================================
# SYNCHRONOUS METHODS (for REST API and Fraxis Socket.IO)
# ============================================================================

@frappe.whitelist()
def test_get_list(doctype, limit_page_length=20, limit_start=0, filters=None, fields=None):
    """
    Whitelisted test method for Socket.IO testing.
    Wraps frappe.client.get_list with proper whitelisting.
    """
    return frappe.client.get_list(
        doctype,
        limit_page_length=limit_page_length,
        limit_start=limit_start,
        filters=filters,
        fields=fields
    )


@frappe.whitelist()
def test_get_value(doctype, name, fieldname=None):
    """
    Whitelisted test method for getting a single document.
    Wraps frappe.client.get_value with proper whitelisting.
    """
    return frappe.client.get_value(doctype, name, fieldname)


@frappe.whitelist()
def test_count(doctype, filters=None):
    """
    Whitelisted test method for counting documents.
    """
    return frappe.db.count(doctype, filters)


# ============================================================================
# ASYNC METHODS (ONLY for Fraxis Socket.IO - NOT callable via REST API)
# ============================================================================

@frappe.whitelist()
async def async_simple_operation(value: int = 1) -> dict:
    """
    Pattern 1: Simple async method with simulated I/O delay.
    
    This demonstrates:
    - Basic async/await syntax
    - Non-blocking sleep (simulating I/O)
    - Return value from async method
    
    Socket.IO: method:execute
    Duration:  < 2 seconds
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    """
    # Simulate I/O delay without blocking the event loop
    await asyncio.sleep(0.5)
    
    result = value * 2
    
    return {
        'input': value,
        'output': result,
        'operation': 'multiply_by_2',
        'async': True
    }


@frappe.whitelist()
async def async_frappe_orm_operation(doctype: str, limit: int = 5) -> dict:
    """
    Pattern 2: Async method with Frappe ORM calls (direct, accepting brief blocking).
    
    This demonstrates:
    - Fast Frappe ORM calls (<100ms) can be called directly in async methods
    - Brief event loop blocking is acceptable for quick database queries
    - This is simpler and avoids thread-safety issues with DB connections
    
    Socket.IO: method:execute
    Duration:  < 2 seconds
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    NOTE: For heavy queries, consider using method:enqueue instead.
    """
    # Simulate async I/O first
    await asyncio.sleep(0.1)
    
    # Fast Frappe ORM calls - acceptable to block briefly
    count = frappe.db.count(doctype)
    
    docs = frappe.get_all(
        doctype,
        fields=['name'],
        limit_page_length=limit
    )
    
    # Another async delay to show non-blocking behavior
    await asyncio.sleep(0.1)
    
    return {
        'doctype': doctype,
        'total_count': count,
        'sample_docs': docs,
        'limit': limit,
        'async': True
    }


@frappe.whitelist()
async def async_concurrent_operations(doctypes=None) -> dict:
    """
    Pattern 3: Async method with concurrent async I/O operations.
    
    This demonstrates:
    - Running multiple I/O operations concurrently with asyncio.gather()
    - True async benefit: all delays happen in parallel
    - Combining results from multiple async tasks
    
    Socket.IO: method:execute
    Duration:  bounded by slowest operation, all run concurrently
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    NOTE: Uses simulated delays instead of DB calls to avoid thread-safety issues.
    """
    if doctypes is None:
        doctypes = ['ToDo', 'User', 'DocType']
    
    # Define an async task with simulated work
    async def process_doctype(dt):
        # Simulate async I/O work
        await asyncio.sleep(0.2)
        # Quick DB call - acceptable brief blocking
        try:
            count = frappe.db.count(dt)
            return {dt: count}
        except Exception as e:
            return {'error': str(e), 'doctype': dt}
    
    # Run all operations concurrently
    tasks = [process_doctype(dt) for dt in doctypes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    counts = {}
    errors = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            errors.append({
                'doctype': doctypes[i],
                'error': str(result)
            })
        elif isinstance(result, dict):
            if 'error' in result:
                errors.append(result)
            else:
                counts.update(result)
    
    return {
        'counts': counts,
        'errors': errors,
        'total_doctypes': len(doctypes),
        'async': True,
        'concurrent': True
    }


@frappe.whitelist()
async def async_mixed_operations(doctype: str, delay: float = 0.5) -> dict:
    """
    Pattern 4: Async method mixing true async I/O with Frappe ORM.
    
    This demonstrates:
    - Combining asyncio.sleep() (true async) with Frappe ORM (direct calls)
    - Sequential async operations
    - Proper error handling in async context
    
    Socket.IO: method:execute
    Duration:  delay + DB operation time
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    """
    start_time = asyncio.get_event_loop().time()
    
    # True async I/O - simulates external API call
    await asyncio.sleep(delay)
    
    # Fast Frappe ORM calls - acceptable brief blocking
    count = frappe.db.count(doctype)
    
    # Another async delay
    await asyncio.sleep(0.1)
    
    # Another ORM call
    sample = frappe.get_all(
        doctype,
        fields=['name'],
        limit_page_length=1
    )
    
    end_time = asyncio.get_event_loop().time()
    elapsed = end_time - start_time
    
    return {
        'doctype': doctype,
        'count': count,
        'sample': sample,
        'elapsed_seconds': round(elapsed, 3),
        'delay_requested': delay,
        'async': True
    }


@frappe.whitelist()
async def async_error_handling(should_fail: bool = False, error_type: str = 'runtime') -> dict:
    """
    Pattern 5: Async method with error handling.
    
    This demonstrates:
    - Proper exception handling in async methods
    - Different types of errors (validation, runtime, DB)
    - Error propagation to Fraxis response envelope
    
    Socket.IO: method:execute
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    """
    if not should_fail:
        await asyncio.sleep(0.1)
        return {
            'status': 'success',
            'message': 'No error requested',
            'async': True
        }
    
    # Trigger different types of errors for testing
    if error_type == 'validation':
        raise frappe.ValidationError('Async validation error triggered')
    elif error_type == 'permission':
        raise frappe.PermissionError('Async permission error triggered')
    elif error_type == 'runtime':
        raise RuntimeError('Async runtime error triggered')
    elif error_type == 'db':
        # Trigger a DB error by trying to access non-existent doctype
        await asyncio.to_thread(frappe.get_doc, 'NonExistentDocType', 'fake-name')
        return {'status': 'error', 'async': True}  # Won't reach here
    else:
        raise ValueError(f'Unknown error_type: {error_type}')


@frappe.whitelist()
async def async_with_progress_simulation(steps: int = 5, progress=None) -> dict:
    """
    Pattern 6: Async method with injected progress callback.
    
    Demonstrates the hybrid Option F approach for in-process async progress.
    The progress callback is injected by MethodNamespace.on_method_execute if present.
    
    Socket.IO: method:execute
    Duration:  steps * 0.2 seconds
    Events:    method:execute:progress (if progress callback is injected)
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    """
    from datetime import datetime
    results = []
    
    for i in range(steps):
        # Simulate async work for each step
        await asyncio.sleep(0.2)
        
        # Collect results
        step_result = {
            'step': i + 1,
            'timestamp': datetime.now().isoformat(),
            'data': f'Step {i + 1} completed'
        }
        results.append(step_result)
        
        # Report progress if callback is injected
        # The callback emits method:execute:progress to the requesting client
        if progress:
            await progress(
                percent=round((i + 1) / steps * 100, 1),
                title="Processing Steps",
                description=f"Step {i + 1} of {steps}",
                data=step_result  # arbitrary payload - streaming partial results
            )
    
    return {
        'total_steps': steps,
        'results': results,
        'async': True
    }


# ============================================================================
# LONG-RUNNING BACKGROUND JOBS (via RQ)
# ============================================================================

@frappe.whitelist()
def long_running_sync_job(iterations: int = 10) -> dict:
    """
    Pattern 7: Long-running synchronous method for background execution via RQ.
    
    Demonstrates the hybrid Option F approach for out-of-process RQ progress.
    Uses fraxis.utils.realtime.publish_progress() which extends frappe's version
    with support for arbitrary `data` payloads.
    
    This should be called via method:enqueue, NOT method:execute.
    
    Socket.IO: method:enqueue
    Duration:  iterations * 0.5 seconds
    Events:    method:enqueue:progress (relayed via Redis pub/sub)
    """
    from datetime import datetime
    import time
    from fraxis.utils.realtime import publish_progress
    
    results = []
    
    for i in range(iterations):
        # Simulate work
        time.sleep(0.5)
        
        # Collect iteration result
        iteration_result = {
            'iteration': i + 1,
            'timestamp': datetime.now().isoformat()
        }
        results.append(iteration_result)
        
        # Publish progress with arbitrary data payload
        # This emits directly to Socket.IO rooms via AsyncRedisManager (write-only)
        # No translation needed - RQ worker publishes directly to Fraxis event taxonomy
        publish_progress(
            percent=round((i + 1) / iterations * 100, 1),
            title="Processing Long Job",
            description=f"Completed iteration {i + 1} of {iterations}",
            data=iteration_result  # arbitrary payload - streaming partial results
        )
    
    return {
        'total_iterations': iterations,
        'results': results,
        'completed': True
    }


# ============================================================================
# ASYNC ITERATOR METHODS (ONLY for Fraxis Socket.IO - NOT callable via REST API)
# ============================================================================

@frappe.whitelist()
async def get_async_iterator(values: List[str], min_ms: int = 100, max_ms: int = 300) -> AsyncIterator[str]:
    """
    Pattern 8: Async generator that yields values with random delays.
    
    This demonstrates:
    - AsyncIterator pattern for streaming data
    - Random delays to simulate real-world async I/O
    - Yielding values incrementally as they become available
    
    Args:
        values: List of strings to yield
        min_ms: Minimum delay in milliseconds between yields
        max_ms: Maximum delay in milliseconds between yields
    
    Yields:
        str: Each value from the input list after a random delay
    
    Raises:
        ValueError: If min_ms or max_ms are negative, or min_ms > max_ms
    
    Socket.IO: method:execute (with AsyncIterator support)
    Duration: sum of random delays for all values
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    NOTE: Requires AsyncIterator support in MethodNamespace.
    """
    if min_ms < 0 or max_ms < 0:
        raise ValueError("min_ms and max_ms must be non-negative")
    if min_ms > max_ms:
        raise ValueError("min_ms must be <= max_ms")
    
    for value in values:
        # Sleep a random time between min_ms and max_ms (converted to seconds)
        delay_s = random.uniform(min_ms, max_ms) / 1000.0
        await asyncio.sleep(delay_s)
        yield value


@frappe.whitelist()
async def process_values(values: List[str], min_ms: int = 100, max_ms: int = 300, progress=None) -> dict:
    """
    Pattern 9: Async method that consumes an AsyncIterator and reports progress.
    
    This demonstrates:
    - Consuming an async generator (AsyncIterator)
    - Calculating time deltas between yields
    - Emitting progress events for each received value
    - Using the injected progress callback to stream partial results
    
    The method acquires an async iterator via get_async_iterator and iterates it,
    emitting progress events with timing information for each value received.
    
    Args:
        values: List of strings to process
        min_ms: Minimum delay in milliseconds for the async iterator
        max_ms: Maximum delay in milliseconds for the async iterator
        progress: Injected progress callback (optional, provided by MethodNamespace)
    
    Returns:
        dict: Summary with total values processed, elapsed time, and all results
    
    Socket.IO: method:execute
    Duration: sum of random delays for all values
    Events: method:execute:progress (if progress callback is injected)
    NOTE: Only works via Fraxis Socket.IO, NOT via Frappe REST API.
    """
    from datetime import datetime
    
    # Get the async iterator
    values_aiter = get_async_iterator(values, min_ms=min_ms, max_ms=max_ms)
    
    # Track timing
    start_time = asyncio.get_event_loop().time()
    prev_time = start_time
    
    # Collect results
    results = []
    
    # Iterate through the async generator
    async for value in values_aiter:
        now = asyncio.get_event_loop().time()
        delta_ms = (now - prev_time) * 1000.0
        
        # Record result with timing information
        result_entry = {
            'value': value,
            'delta_ms': round(delta_ms, 3),
            'timestamp': datetime.now().isoformat()
        }
        results.append(result_entry)
        
        # Report progress if callback is injected
        if progress:
            percent = round((len(results) / len(values)) * 100, 1)
            await progress(
                percent=percent,
                title="Processing Values",
                description=f"Received value: {value} (+{delta_ms:.3f} ms)",
                data=result_entry  # Stream partial results
            )
        
        # Update previous time for next delta calculation
        prev_time = now
    
    # Calculate total elapsed time
    end_time = asyncio.get_event_loop().time()
    total_elapsed_ms = (end_time - start_time) * 1000.0
    
    return {
        'total_values': len(values),
        'results': results,
        'total_elapsed_ms': round(total_elapsed_ms, 3),
        'async': True,
        'async_iterator': True
    }
