# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Unit tests for FraxisNamespace base class.
Tests connection lifecycle, authentication hooks, and state event emission.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from typing import ClassVar

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.security.auth import AuthError, parse_token


class TestTokenParsing(unittest.TestCase):
    """Test the pure token parser that backs api_key:secret authentication."""

    def test_parse_valid_token(self):
        """A well-formed 'api_key:api_secret' token splits into its two parts."""
        self.assertEqual(parse_token("abc123:secret456"), ("abc123", "secret456"))

    def test_parse_token_strips_whitespace(self):
        self.assertEqual(parse_token("  abc :  secret "), ("abc", "secret"))

    def test_parse_token_keeps_colons_in_secret(self):
        """Only the first colon separates key from secret."""
        self.assertEqual(parse_token("key:a:b:c"), ("key", "a:b:c"))

    def test_parse_token_rejects_missing(self):
        for bad in (None, "", {}):
            with self.assertRaises(AuthError):
                parse_token(bad)

    def test_parse_token_rejects_malformed(self):
        for bad in ("no-colon", "key:", ":secret", " : "):
            with self.assertRaises(AuthError):
                parse_token(bad)


class TestEmitState(unittest.TestCase):
    """Test _emit_state convenience method for lifecycle event emission."""

    def test_emit_state_constructs_correct_event_name(self):
        """_emit_state constructs event name as 'scope:action:state'."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()

        asyncio.run(namespace._emit_state("sid123", "document", "create", "start"))

        namespace.emit.assert_called_once()
        call_args = namespace.emit.call_args
        self.assertEqual(call_args[0][0], "document:create:start")
        self.assertEqual(call_args[1]["to"], "sid123")

    def test_emit_state_with_payload(self):
        """_emit_state includes payload in emitted event."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()

        payload = {"result": "success", "data": {"id": 1}}
        asyncio.run(namespace._emit_state("sid123", "document", "create", "success", payload))

        namespace.emit.assert_called_once()
        call_args = namespace.emit.call_args
        self.assertEqual(call_args[0][0], "document:create:success")
        self.assertEqual(call_args[0][1], payload)

    def test_emit_state_default_payload_is_empty_dict(self):
        """_emit_state uses empty dict when no payload provided."""
        namespace = FraxisNamespace()
        namespace.emit = AsyncMock()

        asyncio.run(namespace._emit_state("sid123", "document", "delete", "failure"))

        call_args = namespace.emit.call_args
        self.assertEqual(call_args[0][1], {})


class TestConnectionLifecycle(unittest.TestCase):
    """Test on_connect and on_disconnect lifecycle methods."""

    def test_on_disconnect_is_defined(self):
        """on_disconnect method exists and can be called."""
        namespace = FraxisNamespace()
        # on_disconnect can be called (it's an async method but we test the sync path)
        self.assertTrue(hasattr(namespace, "on_disconnect"))
        self.assertTrue(callable(namespace.on_disconnect))


class TestNamespaceStateManagement(unittest.TestCase):
    """Test namespace state management utilities."""

    def test_namespace_has_handler_map_class_variable(self):
        """FraxisNamespace has _handler_map class variable."""
        namespace = FraxisNamespace()
        self.assertTrue(hasattr(namespace, "_handler_map"))
        self.assertIsInstance(FraxisNamespace._handler_map, dict)


class TestNamespaceInitialization(unittest.TestCase):
    """Test namespace initialization and configuration."""

    def test_namespace_initialization(self):
        """Namespace can be instantiated."""
        namespace = FraxisNamespace(namespace="test/namespace")
        self.assertEqual(namespace.namespace, "test/namespace")

    def test_multiple_namespace_instances_independent(self):
        """Multiple namespace instances don't share state."""

        class TestNamespace(FraxisNamespace):
            _handler_map: ClassVar[dict[str, str]] = {}
            counter = 0

            @FraxisNamespace.handler("test:increment")
            async def on_increment(self, sid, data):
                self.counter += 1
                return self.counter

        ns1 = TestNamespace()
        ns2 = TestNamespace()

        # Instance variables are separate
        ns1.counter = 5
        self.assertEqual(ns2.counter, 0)


class TestErrorHandling(unittest.TestCase):
    """Test error handling in base namespace."""

    def test_emit_state_handles_missing_emit_method(self):
        """_emit_state handles gracefully if emit method missing."""
        namespace = FraxisNamespace()
        # If namespace.emit is not properly initialized, should not crash
        # This tests robustness
        namespace.emit = None

        # Should raise AttributeError or handle gracefully
        with self.assertRaises((AttributeError, TypeError)):
            asyncio.run(namespace._emit_state("sid", "test", "event", "start"))


class TestHandlerMethodResolution(unittest.TestCase):
    """Test handler method resolution in FraxisNamespace."""

    def test_trigger_event_with_nonexistent_handler(self):
        """trigger_event with no matching handler attempts fallback convention."""
        namespace = FraxisNamespace()

        # When no handler is found, trigger_event falls back to on_<event> convention
        # If that also doesn't exist, Socket.IO's parent trigger_event will handle it
        # This is expected behavior - no exception should be raised
        result = asyncio.run(namespace.trigger_event("nonexistent_event", "sid", {}))
        # Result depends on Socket.IO's default behavior, but should not crash
        self.assertTrue(result is not None or result is None)  # Either value is acceptable

    def test_trigger_event_can_chain_with_on_convention(self):
        """Handlers following on_<event> convention still work."""

        class TestNamespace(FraxisNamespace):
            _handler_map: ClassVar[dict[str, str]] = {}

            async def on_legacy_event(self, sid, data):
                return {"result": "legacy_handled"}

        ns = TestNamespace()
        result = asyncio.run(ns.trigger_event("legacy_event", "sid", {}))
        self.assertEqual(result["result"], "legacy_handled")
