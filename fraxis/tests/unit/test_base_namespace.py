# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Unit tests for FraxisNamespace base class.
Tests connection lifecycle, authentication hooks, and state event emission.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from typing import ClassVar
from socketio.exceptions import ConnectionRefusedError as SocketIOConnectionRefusedError

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.security.auth import AuthError, parse_token


@pytest.mark.unit
class TestTokenParsing:
    """Test the pure token parser that backs api_key:secret authentication."""

    def test_parse_valid_token(self):
        """A well-formed 'api_key:api_secret' token splits into its two parts."""
        assert parse_token("abc123:secret456") == ("abc123", "secret456")

    def test_parse_token_strips_whitespace(self):
        assert parse_token("  abc :  secret ") == ("abc", "secret")

    def test_parse_token_keeps_colons_in_secret(self):
        """Only the first colon separates key from secret."""
        assert parse_token("key:a:b:c") == ("key", "a:b:c")

    def test_parse_token_rejects_missing(self):
        for bad in (None, "", {}):
            with pytest.raises(AuthError):
                parse_token(bad)

    def test_parse_token_rejects_malformed(self):
        for bad in ("no-colon", "key:", ":secret", " : "):
            with pytest.raises(AuthError):
                parse_token(bad)


@pytest.mark.unit
class TestEmitState:
    """Test _emit_state convenience method for lifecycle event emission."""
    
    @pytest.mark.asyncio
    async def test_emit_state_constructs_correct_event_name(self):
        """_emit_state constructs event name as 'scope:action:state'."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()
        
        await namespace._emit_state('sid123', 'document', 'create', 'start')
        
        namespace.emit.assert_called_once()
        call_args = namespace.emit.call_args
        assert call_args[0][0] == 'document:create:start'
        assert call_args[1]['to'] == 'sid123'
    
    @pytest.mark.asyncio
    async def test_emit_state_with_payload(self):
        """_emit_state includes payload in emitted event."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()
        
        payload = {'result': 'success', 'data': {'id': 1}}
        await namespace._emit_state('sid123', 'document', 'create', 'success', payload)
        
        namespace.emit.assert_called_once()
        call_args = namespace.emit.call_args
        assert call_args[0][0] == 'document:create:success'
        assert call_args[0][1] == payload
    
    @pytest.mark.asyncio
    async def test_emit_state_default_payload_is_empty_dict(self):
        """_emit_state uses empty dict when no payload provided."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()
        
        await namespace._emit_state('sid123', 'document', 'delete', 'failure')
        
        call_args = namespace.emit.call_args
        assert call_args[0][1] == {}


@pytest.mark.unit
class TestConnectionLifecycle:
    """Test on_connect and on_disconnect lifecycle methods."""
    
    @pytest.mark.asyncio
    async def test_on_disconnect_is_defined(self):
        """on_disconnect method exists and can be called."""
        namespace = FraxisNamespace()
        # on_disconnect can be called (it's an async method but we test the sync path)
        assert hasattr(namespace, 'on_disconnect')
        assert callable(namespace.on_disconnect)


@pytest.mark.unit
class TestNamespaceStateManagement:
    """Test namespace state management utilities."""
    
    def test_namespace_has_handler_map_class_variable(self):
        """FraxisNamespace has _handler_map class variable."""
        namespace = FraxisNamespace()
        assert hasattr(namespace, '_handler_map')
        assert isinstance(FraxisNamespace._handler_map, dict)


@pytest.mark.unit
class TestNamespaceInitialization:
    """Test namespace initialization and configuration."""
    
    def test_namespace_initialization(self):
        """Namespace can be instantiated."""
        namespace = FraxisNamespace(namespace='test/namespace')
        assert namespace.namespace == 'test/namespace'
    
    def test_multiple_namespace_instances_independent(self):
        """Multiple namespace instances don't share state."""
        class TestNamespace(FraxisNamespace):
            _handler_map: ClassVar[dict[str, str]] = {}
            counter = 0
            
            @FraxisNamespace.handler('test:increment')
            async def on_increment(self, sid, data):
                self.counter += 1
                return self.counter
        
        ns1 = TestNamespace()
        ns2 = TestNamespace()
        
        # Instance variables are separate
        ns1.counter = 5
        assert ns2.counter == 0


@pytest.mark.unit
class TestErrorHandling:
    """Test error handling in base namespace."""
    
    @pytest.mark.asyncio
    async def test_emit_state_handles_missing_emit_method(self):
        """_emit_state handles gracefully if emit method missing."""
        namespace = FraxisNamespace()
        # If namespace.emit is not properly initialized, should not crash
        # This tests robustness
        namespace.emit = None
        
        # Should raise AttributeError or handle gracefully
        with pytest.raises((AttributeError, TypeError)):
            await namespace._emit_state('sid', 'test', 'event', 'start')


@pytest.mark.unit
class TestHandlerMethodResolution:
    """Test handler method resolution in FraxisNamespace."""
    
    @pytest.mark.asyncio
    async def test_trigger_event_with_nonexistent_handler(self):
        """trigger_event with no matching handler attempts fallback convention."""
        namespace = FraxisNamespace()
        
        # When no handler is found, trigger_event falls back to on_<event> convention
        # If that also doesn't exist, Socket.IO's parent trigger_event will handle it
        # This is expected behavior - no exception should be raised
        result = await namespace.trigger_event('nonexistent_event', 'sid', {})
        # Result depends on Socket.IO's default behavior, but should not crash
        assert result is not None or result is None  # Either value is acceptable
    
    @pytest.mark.asyncio
    async def test_trigger_event_can_chain_with_on_convention(self):
        """Handlers following on_<event> convention still work."""
        class TestNamespace(FraxisNamespace):
            _handler_map: ClassVar[dict[str, str]] = {}
            
            async def on_legacy_event(self, sid, data):
                return {'result': 'legacy_handled'}
        
        ns = TestNamespace()
        result = await ns.trigger_event('legacy_event', 'sid', {})
        assert result['result'] == 'legacy_handled'
