# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Main pytest configuration and shared fixtures for Fraxis testing.
Provides database setup, mocking utilities, and test data.
"""

import pytest
import asyncio
import frappe
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Generator
from datetime import datetime

# Add fraxis to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (asyncio test)"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_frappe_test_environment():
    """Setup Frappe test environment."""
    try:
        # Ensure Frappe is initialized
        if not frappe.get_site():
            frappe.init(site='test_site')
        yield
    except Exception as e:
        print(f"Warning: Could not setup Frappe test environment: {e}")
        yield


# ============================================================================
# MOCKING FIXTURES
# ============================================================================

@pytest.fixture
def mock_frappe():
    """Fixture providing mocked frappe module for unit tests."""
    with patch('fraxis.fraxis_socket_io.base.frappe') as mock_f:
        # Setup common mocked methods
        mock_f.has_permission = MagicMock(return_value=True)
        mock_f.get_doc = MagicMock()
        mock_f.new_doc = MagicMock()
        mock_f.set_user = MagicMock()
        mock_f.init = MagicMock()
        mock_f.destroy = MagicMock()
        mock_f.db = MagicMock()
        mock_f.db.commit = MagicMock()
        mock_f.session = MagicMock()
        mock_f.session.user = 'test_user'
        mock_f.local = MagicMock()
        mock_f.local.site = 'test_site'
        mock_f.PermissionError = frappe.PermissionError
        mock_f.ValidationError = frappe.ValidationError
        
        yield mock_f


@pytest.fixture
def mock_socketio_namespace():
    """Fixture providing mocked Socket.IO namespace."""
    from socketio import AsyncNamespace
    
    namespace = MagicMock(spec=AsyncNamespace)
    namespace.emit = AsyncMock()
    namespace.enter_room = AsyncMock()
    namespace.leave_room = AsyncMock()
    namespace.to = MagicMock(return_value=namespace)
    
    yield namespace


@pytest.fixture
def mock_socketio_server():
    """Fixture providing mocked Socket.IO server."""
    from socketio import AsyncServer
    
    server = MagicMock(spec=AsyncServer)
    server.emit = AsyncMock()
    server.enter_room = AsyncMock()
    server.leave_room = AsyncMock()
    server.to = MagicMock(return_value=server)
    
    yield server


# ============================================================================
# TEST DATA FIXTURES
# ============================================================================

@pytest.fixture
def test_todo_data() -> dict:
    """Fixture providing test ToDo document data."""
    return {
        'doctype': 'ToDo',
        'data': {
            'title': 'Test Task',
            'description': 'This is a test task',
            'status': 'Open'
        }
    }


@pytest.fixture
def test_auth_token() -> dict:
    """Fixture providing test authentication token."""
    return {'token': 'test_valid_token_12345'}


@pytest.fixture
def test_invalid_auth_token() -> dict:
    """Fixture providing invalid authentication token."""
    return {'token': 'test_invalid_token'}


# ============================================================================
# HELPER UTILITIES
# ============================================================================

@pytest.fixture
def create_test_doc_factory():
    """Factory fixture for creating test documents."""
    created_docs = []
    
    def _create_doc(doctype: str, **kwargs) -> dict:
        """Create a test document and track it for cleanup."""
        try:
            doc = frappe.new_doc(doctype)
            doc.update(kwargs)
            doc.insert()
            frappe.db.commit()
            created_docs.append((doctype, doc.name))
            return doc.as_dict()
        except Exception as e:
            print(f"Error creating test doc: {e}")
            return None
    
    yield _create_doc
    
    # Cleanup
    for doctype, name in reversed(created_docs):
        try:
            frappe.delete_doc(doctype, name)
            frappe.db.commit()
        except:
            pass


# ============================================================================
# ASYNC UTILITIES
# ============================================================================

@pytest.fixture
def async_test_helper():
    """Fixture providing async testing utilities."""
    class AsyncTestHelper:
        @staticmethod
        async def wait_for(condition, timeout=5, interval=0.1):
            """Wait for a condition to be true."""
            import time
            start = time.time()
            while time.time() - start < timeout:
                if condition():
                    return True
                await asyncio.sleep(interval)
            return False
        
        @staticmethod
        async def gather_with_timeout(*coros, timeout=5):
            """Gather coroutines with timeout."""
            try:
                return await asyncio.wait_for(
                    asyncio.gather(*coros),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                return None
    
    return AsyncTestHelper()


# ============================================================================
# RESPONSE ENVELOPE TEST UTILITIES
# ============================================================================

@pytest.fixture
def response_factory():
    """Fixture providing Response envelope factory."""
    from fraxis.utils.cornerstone.response import Response
    
    class ResponseFactory:
        @staticmethod
        def success_response(data=None, metadata=None):
            """Create a successful response."""
            return Response.success(data=data, metadata=metadata)
        
        @staticmethod
        def failure_response(error="Test error", error_code="TEST_ERROR", details=None):
            """Create a failure response."""
            return Response.failure(
                error=error,
                error_code=error_code,
                details=details
            )
        
        @staticmethod
        def response_with_messages(data=None):
            """Create a response with multiple messages."""
            resp = Response.success(data=data)
            resp.add_warning("Test warning")
            resp.add_info("Test info")
            return resp
    
    return ResponseFactory()


# ============================================================================
# HANDLER REGISTRY TEST UTILITIES
# ============================================================================

@pytest.fixture
def handler_registry_test_class():
    """Fixture providing a test class for handler registry tests."""
    from fraxis.fraxis_socket_io.base import FraxisNamespace
    from typing import ClassVar
    
    class TestNamespace(FraxisNamespace):
        _handler_map: ClassVar[dict[str, str]] = {}
        
        @FraxisNamespace.handler('test:event')
        async def on_test_event(self, sid, data):
            return {'result': 'test_event_handled', 'data': data}
        
        @FraxisNamespace.handler('test:another')
        async def on_test_another(self, sid, data):
            return {'result': 'another_event_handled'}
        
        def sync_method(self, sid, data):
            return {'result': 'sync_handled', 'data': data}
    
    return TestNamespace


# ============================================================================
# SOCKET.IO NAMESPACE TEST UTILITIES
# ============================================================================

@pytest.fixture
def namespace_factory():
    """Fixture providing namespace factory for testing."""
    from fraxis.fraxis_socket_io.namespaces.system import SystemNamespace
    from fraxis.fraxis_socket_io.namespaces.document import DocumentNamespace
    from fraxis.fraxis_socket_io.namespaces.doctype import DoctypeNamespace
    from fraxis.fraxis_socket_io.namespaces.method import MethodNamespace
    
    class NamespaceFactory:
        @staticmethod
        def create_system_namespace():
            return SystemNamespace('/system')
        
        @staticmethod
        def create_document_namespace():
            return DocumentNamespace('/api/document')
        
        @staticmethod
        def create_doctype_namespace():
            return DoctypeNamespace('/api/doctype')
        
        @staticmethod
        def create_method_namespace():
            return MethodNamespace('/api/method')
    
    return NamespaceFactory()
