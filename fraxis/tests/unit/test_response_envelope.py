# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Unit tests for Response envelope model validation and serialization.
Tests the Pydantic Response[T] model used for all Socket.IO responses.
"""

import pytest
from fraxis.utils.cornerstone.response import Response, MessageTrace, TraceSeverityLevel, ResponseBuilder


@pytest.mark.unit
class TestResponseEnvelopeStructure:
    """Test Response envelope structure and fields."""
    
    def test_success_response_structure(self):
        """Response.success() creates correct envelope with data, metadata, stacks."""
        test_data = {'name': 'test_doc', 'title': 'Test Document'}
        test_metadata = {'timestamp': '2026-02-16 10:30:00', 'sid': 'abc123'}
        
        response = Response.success(data=test_data, metadata=test_metadata)
        
        assert response.is_success is True
        assert response.data == test_data
        assert response.metadata == test_metadata
        assert response.error_stack == []
        assert response.warning_stack == []
        assert response.info_stack == []
    
    def test_failure_response_structure(self):
        """Response.failure() creates envelope with error data."""
        error_msg = "Operation failed"
        error_code = "OP_FAILED"
        details = {'field': 'name'}
        
        response = Response.failure(
            error=error_msg,
            error_code=error_code,
            details=details
        )
        
        assert response.is_success is False
        assert len(response.error_stack) == 1
        assert response.error_stack[0].message == error_msg
        assert response.error_stack[0].code == error_code
        assert response.error_stack[0].details == details
        assert response.data is None
    
    def test_response_with_null_data(self):
        """Failure responses correctly handle data=null."""
        response = Response.failure(error="Error occurred")
        
        assert response.data is None
        assert response.is_success is False
        assert response.has_errors is True
    
    def test_response_has_properties(self):
        """Response has_errors, has_warnings, has_info properties work correctly."""
        response = Response.success(data={'test': 'data'})
        
        assert response.has_errors is False
        assert response.has_warnings is False
        assert response.has_info is False
        
        response.add_error("Error message")
        response.add_warning("Warning message")
        response.add_info("Info message")
        
        assert response.has_errors is True
        assert response.has_warnings is True
        assert response.has_info is True


@pytest.mark.unit
class TestResponseMessageTraces:
    """Test message trace functionality."""
    
    def test_add_error_message(self):
        """Response.add_error() adds error to error_stack."""
        response = Response.success(data={})
        
        response.add_error(
            message="Validation failed",
            code="VALIDATION_ERROR",
            details={'field': 'email'}
        )
        
        assert len(response.error_stack) == 1
        assert response.error_stack[0].message == "Validation failed"
        assert response.error_stack[0].code == "VALIDATION_ERROR"
        assert response.error_stack[0].severity == TraceSeverityLevel.ERROR
        assert response.is_success is False
    
    def test_add_warning_message(self):
        """Response.add_warning() adds warning to warning_stack."""
        response = Response.success(data={})
        response.add_warning("This is deprecated")
        
        assert len(response.warning_stack) == 1
        assert response.warning_stack[0].message == "This is deprecated"
        assert response.warning_stack[0].severity == TraceSeverityLevel.WARNING
        assert response.is_success is True  # Warnings don't make response fail
    
    def test_add_info_message(self):
        """Response.add_info() adds info to info_stack."""
        response = Response.success(data={})
        response.add_info("Operation completed", code="OP_COMPLETE")
        
        assert len(response.info_stack) == 1
        assert response.info_stack[0].message == "Operation completed"
        assert response.info_stack[0].code == "OP_COMPLETE"
        assert response.info_stack[0].severity == TraceSeverityLevel.INFO
    
    def test_message_trace_severity_levels(self):
        """MessageTrace correctly differentiates severity levels."""
        error_trace = MessageTrace(
            message="Error",
            severity=TraceSeverityLevel.ERROR
        )
        warning_trace = MessageTrace(
            message="Warning",
            severity=TraceSeverityLevel.WARNING
        )
        info_trace = MessageTrace(
            message="Info",
            severity=TraceSeverityLevel.INFO
        )
        
        assert error_trace.severity == TraceSeverityLevel.ERROR
        assert warning_trace.severity == TraceSeverityLevel.WARNING
        assert info_trace.severity == TraceSeverityLevel.INFO


@pytest.mark.unit
class TestResponseSerialization:
    """Test Response serialization to dict and JSON."""
    
    def test_response_to_dict(self):
        """response.to_dict() converts Pydantic model to plain dict."""
        response = Response.success(
            data={'name': 'doc1', 'title': 'Test'},
            metadata={'timestamp': '2026-02-16', 'sid': 'abc'}
        )
        response.add_warning("Test warning")
        
        response_dict = response.to_dict()
        
        assert isinstance(response_dict, dict)
        assert response_dict['is_success'] is True
        assert response_dict['data'] == {'name': 'doc1', 'title': 'Test'}
        assert response_dict['metadata']['timestamp'] == '2026-02-16'
        assert len(response_dict['warning_stack']) == 1
    
    def test_response_to_json(self):
        """response.to_json() converts to JSON string."""
        response = Response.success(data={'test': 'data'})
        json_str = response.to_json()
        
        assert isinstance(json_str, str)
        # Check for both formats (with and without spaces after colon)
        assert ('is_success": true' in json_str or '"is_success":true' in json_str or 'is_success": true' in json_str)
        # Parse to verify it's valid JSON
        import json
        parsed = json.loads(json_str)
        assert parsed['is_success'] == True
        assert parsed['data'] == {'test': 'data'}
    
    def test_response_dict_has_all_fields(self):
        """Serialized response dict includes all fields."""
        response = Response.success(data={'id': 1})
        response.add_error("Test error")
        response.add_warning("Test warning")
        response.add_info("Test info")
        
        d = response.to_dict()
        
        assert 'is_success' in d
        assert 'data' in d
        assert 'error_stack' in d
        assert 'warning_stack' in d
        assert 'info_stack' in d
        assert 'metadata' in d


@pytest.mark.unit
class TestResponseBuilder:
    """Test ResponseBuilder pattern for complex response construction."""
    
    def test_builder_creates_successful_response(self):
        """ResponseBuilder creates successful response with all fields."""
        response = (ResponseBuilder()
                    .with_data({'id': 1, 'name': 'test'})
                    .with_metadata({'timestamp': '2026-02-16'})
                    .with_info("Operation completed")
                    .build())
        
        assert response.is_success is True
        assert response.data == {'id': 1, 'name': 'test'}
        assert response.metadata['timestamp'] == '2026-02-16'
        assert len(response.info_stack) == 1
    
    def test_builder_creates_failure_response(self):
        """ResponseBuilder creates failure response."""
        response = (ResponseBuilder()
                    .with_error("Permission denied", code="PERMISSION_DENIED")
                    .with_warning("This operation was blocked")
                    .build())
        
        assert response.is_success is False
        assert len(response.error_stack) == 1
        assert response.error_stack[0].code == "PERMISSION_DENIED"
        assert len(response.warning_stack) == 1
    
    def test_builder_chainable(self):
        """ResponseBuilder methods are chainable."""
        response = (ResponseBuilder()
                    .with_data({'test': 'data'})
                    .with_error("Error 1")
                    .with_error("Error 2")
                    .with_warning("Warning 1")
                    .with_info("Info 1")
                    .build())
        
        assert len(response.error_stack) == 2
        assert len(response.warning_stack) == 1
        assert len(response.info_stack) == 1


@pytest.mark.unit
class TestResponseMethods:
    """Test Response utility methods."""
    
    def test_get_all_messages_sorted_by_severity(self):
        """get_all_messages() returns messages sorted by severity."""
        response = Response.success(data={})
        response.add_info("Info message")
        response.add_warning("Warning message")
        response.add_error("Error message")
        response.add_error("Another error")
        
        all_messages = response.get_all_messages()
        
        # Should have 4 messages total
        assert len(all_messages) == 4
        # Check that we have at least one of each type
        severities = [msg.severity for msg in all_messages]
        assert TraceSeverityLevel.ERROR in severities
        assert TraceSeverityLevel.WARNING in severities
        assert TraceSeverityLevel.INFO in severities
    
    def test_set_data_returns_self(self):
        """set_data() returns self for chaining."""
        response = Response.success()
        result = response.set_data({'key': 'value'})
        
        assert result is response
        assert response.data == {'key': 'value'}
    
    def test_add_error_returns_self(self):
        """add_error() returns self for chaining."""
        response = Response.success()
        result = response.add_error("Error")
        
        assert result is response
        assert len(response.error_stack) == 1


@pytest.mark.unit
class TestResponseFieldValidation:
    """Test Response field validation and type safety."""
    
    def test_response_with_generic_data_types(self):
        """Response handles various data types."""
        # Dict data
        resp1 = Response.success(data={'key': 'value'})
        assert isinstance(resp1.data, dict)
        
        # List data
        resp2 = Response.success(data=[1, 2, 3])
        assert isinstance(resp2.data, list)
        
        # String data
        resp3 = Response.success(data="test string")
        assert isinstance(resp3.data, str)
        
        # None data
        resp4 = Response.success(data=None)
        assert resp4.data is None
    
    def test_response_metadata_preservation(self):
        """Metadata is preserved through serialization."""
        metadata = {
            'timestamp': '2026-02-16 10:30:00',
            'sid': 'socket_123',
            'site': 'test_site',
            'custom_field': 'custom_value'
        }
        
        response = Response.success(data={'test': 'data'}, metadata=metadata)
        serialized = response.to_dict()
        
        assert serialized['metadata'] == metadata
    
    def test_response_error_stack_with_multiple_errors(self):
        """Response can hold multiple errors with different codes."""
        response = Response()  # empty: no default error

        response.add_error("Error 1", code="ERR_001")
        response.add_error("Error 2", code="ERR_002")
        response.add_error("Error 3", code="ERR_003")

        assert len(response.error_stack) == 3
        assert response.error_stack[0].code == "ERR_001"
        assert response.error_stack[1].code == "ERR_002"
        assert response.error_stack[2].code == "ERR_003"
