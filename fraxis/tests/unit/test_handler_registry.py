# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Unit tests for handler registry decorator mechanism.
Tests the @handler('event:name') decorator that allows event names with colons
to be properly dispatched to handler methods.
"""

import pytest
import asyncio
from typing import ClassVar

from fraxis.fraxis_socket_io.base import FraxisNamespace


@pytest.mark.unit
class TestHandlerDecorator:
    """Test @handler decorator registration mechanism."""
    
    def test_handler_decorator_can_be_called(self):
        """@handler decorator can be applied to methods."""
        # This should not raise an error
        class TestNamespace(FraxisNamespace):
            @FraxisNamespace.handler('test:event')
            async def on_test_event(self, sid, data):
                return {'result': 'ok'}
        
        # Class should be created successfully
        assert TestNamespace is not None
    
    def test_handler_method_is_preserved(self):
        """@handler decorator preserves the original method."""
        class TestNamespace(FraxisNamespace):
            @FraxisNamespace.handler('test:event')
            async def on_test_event(self, sid, data):
                return {'result': 'ok'}
        
        ns = TestNamespace()
        method = ns.on_test_event
        
        # Method should still be callable
        assert callable(method)
        # Method should still be a coroutine function
        assert asyncio.iscoroutinefunction(method)


@pytest.mark.unit
class TestTriggerEvent:
    """Test trigger_event method that uses handler_map."""
    
    @pytest.mark.asyncio
    async def test_trigger_event_resolves_handler(self):
        """trigger_event can resolve and call registered handlers."""
        class TestNamespace(FraxisNamespace):
            @FraxisNamespace.handler('test:event')
            async def on_test_event(self, sid, data):
                return {'result': 'test_event_handled', 'data': data}
        
        namespace = TestNamespace()
        sid = 'test_socket_123'
        data = {'key': 'value'}
        
        # Trigger event
        result = await namespace.trigger_event('test:event', sid, data)
        
        # Should get a result
        assert result is not None
        assert result['result'] == 'test_event_handled'
        assert result['data'] == data
    
    @pytest.mark.asyncio
    async def test_trigger_event_handles_async_methods(self):
        """Async methods are properly awaited."""
        class TestNamespace(FraxisNamespace):
            call_count = 0
            
            @FraxisNamespace.handler('test:async')
            async def on_async_event(self, sid, data):
                self.call_count += 1
                await asyncio.sleep(0.01)
                return {'type': 'async', 'count': self.call_count}
        
        ns = TestNamespace()
        
        # Trigger async event
        result = await ns.trigger_event('test:async', 'sid', {})
        assert result['type'] == 'async'
        assert result['count'] == 1
    
    @pytest.mark.asyncio
    async def test_trigger_event_fallback_to_default_convention(self):
        """Events not in handler_map fall back to on_<event> convention."""
        class TestNamespace(FraxisNamespace):
            async def on_fallback_event(self, sid, data):
                return {'result': 'fallback_handled', 'data': data}
        
        ns = TestNamespace()
        data = {'test': 'data'}
        
        # Trigger event that's NOT explicitly registered
        result = await ns.trigger_event('fallback_event', 'sid', data)
        
        assert result['result'] == 'fallback_handled'
        assert result['data'] == data


@pytest.mark.unit
class TestHandlerDispatch:
    """Test handler dispatch and invocation."""
    
    @pytest.mark.asyncio
    async def test_multiple_handlers_different_events(self):
        """Multiple handlers can be registered for different events."""
        class TestNamespace(FraxisNamespace):
            invoked_events = []
            
            @FraxisNamespace.handler('event:a')
            async def on_event_a(self, sid, data):
                self.invoked_events.append('a')
                return 'event_a'
            
            @FraxisNamespace.handler('event:b')
            async def on_event_b(self, sid, data):
                self.invoked_events.append('b')
                return 'event_b'
            
            @FraxisNamespace.handler('event:c')
            async def on_event_c(self, sid, data):
                self.invoked_events.append('c')
                return 'event_c'
        
        ns = TestNamespace()
        
        result_a = await ns.trigger_event('event:a', 'sid', {})
        result_b = await ns.trigger_event('event:b', 'sid', {})
        result_c = await ns.trigger_event('event:c', 'sid', {})
        
        assert result_a == 'event_a'
        assert result_b == 'event_b'
        assert result_c == 'event_c'
        assert ns.invoked_events == ['a', 'b', 'c']
    
    @pytest.mark.asyncio
    async def test_handler_receives_correct_arguments(self):
        """Handler receives sid, data arguments correctly."""
        class TestNamespace(FraxisNamespace):
            received_args = {}
            
            @FraxisNamespace.handler('test:event')
            async def on_test(self, sid, data):
                self.received_args = {
                    'sid': sid,
                    'data': data
                }
                return 'ok'
        
        ns = TestNamespace()
        test_sid = 'socket_abc123'
        test_data = {'key': 'value', 'number': 42}
        
        await ns.trigger_event('test:event', test_sid, test_data)
        
        assert ns.received_args['sid'] == test_sid
        assert ns.received_args['data'] == test_data


@pytest.mark.unit
class TestHandlerMapEdgeCases:
    """Test edge cases in handler registry."""
    
    @pytest.mark.asyncio
    async def test_handler_with_exception(self):
        """Handler exceptions are propagated."""
        class TestNamespace(FraxisNamespace):
            @FraxisNamespace.handler('test:event')
            async def on_error_event(self, sid, data):
                raise ValueError("Intentional error")
        
        ns = TestNamespace()
        
        with pytest.raises(ValueError, match="Intentional error"):
            await ns.trigger_event('test:event', 'sid', {})
    
    @pytest.mark.asyncio
    async def test_handler_can_be_sync_or_async(self):
        """Handlers can be either async or sync methods."""
        class TestNamespace(FraxisNamespace):
            @FraxisNamespace.handler('test:sync')
            def on_sync_event(self, sid, data):
                return {'type': 'sync', 'data': data}
            
            @FraxisNamespace.handler('test:async')
            async def on_async_event(self, sid, data):
                return {'type': 'async', 'data': data}
        
        ns = TestNamespace()
        
        # Both should work
        sync_result = await ns.trigger_event('test:sync', 'sid', {'key': 'val'})
        async_result = await ns.trigger_event('test:async', 'sid', {'key': 'val'})
        
        assert sync_result['type'] == 'sync'
        assert async_result['type'] == 'async'


@pytest.mark.unit
class TestNamespaceIntegration:
    """Test integration with actual Fraxis namespaces."""
    
    @pytest.mark.asyncio
    async def test_actual_system_namespace_has_handlers(self):
        """Actual SystemNamespace has registered handlers."""
        from fraxis.fraxis_socket_io.namespaces import SystemNamespace
        
        # Create an instance
        ns = SystemNamespace()
        
        # Handlers should be defined or fall back to convention
        assert hasattr(ns, 'on_system_ping')
        assert hasattr(ns, 'on_system_health')
    
    @pytest.mark.asyncio
    async def test_fraxis_namespace_base_has_handler_method(self):
        """FraxisNamespace has the handler method."""
        assert hasattr(FraxisNamespace, 'handler')
        assert callable(FraxisNamespace.handler)

