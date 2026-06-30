# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Unit tests for Response envelope model validation and serialization.
Tests the Pydantic Response[T] model used for all Socket.IO responses.
"""

import json
import unittest

from fraxis.utils.cornerstone.response import (
    Response,
    MessageTrace,
    TraceSeverityLevel,
    ResponseBuilder,
)


class TestResponseEnvelopeStructure(unittest.TestCase):
    """Test Response envelope structure and fields."""

    def test_success_response_structure(self):
        """Response.success() creates correct envelope with data, metadata, stacks."""
        test_data = {"name": "test_doc", "title": "Test Document"}
        test_metadata = {"timestamp": "2026-02-16 10:30:00", "sid": "abc123"}

        response = Response.success(data=test_data, metadata=test_metadata)

        self.assertTrue(response.is_success)
        self.assertEqual(response.data, test_data)
        self.assertEqual(response.metadata, test_metadata)
        self.assertEqual(response.error_stack, [])
        self.assertEqual(response.warning_stack, [])
        self.assertEqual(response.info_stack, [])

    def test_failure_response_structure(self):
        """Response.failure() creates envelope with error data."""
        error_msg = "Operation failed"
        error_code = "OP_FAILED"
        details = {"field": "name"}

        response = Response.failure(error=error_msg, error_code=error_code, details=details)

        self.assertFalse(response.is_success)
        self.assertEqual(len(response.error_stack), 1)
        self.assertEqual(response.error_stack[0].message, error_msg)
        self.assertEqual(response.error_stack[0].code, error_code)
        self.assertEqual(response.error_stack[0].details, details)
        self.assertIsNone(response.data)

    def test_response_with_null_data(self):
        """Failure responses correctly handle data=null."""
        response = Response.failure(error="Error occurred")

        self.assertIsNone(response.data)
        self.assertFalse(response.is_success)
        self.assertTrue(response.has_errors)

    def test_response_has_properties(self):
        """Response has_errors, has_warnings, has_info properties work correctly."""
        response = Response.success(data={"test": "data"})

        self.assertFalse(response.has_errors)
        self.assertFalse(response.has_warnings)
        self.assertFalse(response.has_info)

        response.add_error("Error message")
        response.add_warning("Warning message")
        response.add_info("Info message")

        self.assertTrue(response.has_errors)
        self.assertTrue(response.has_warnings)
        self.assertTrue(response.has_info)


class TestResponseMessageTraces(unittest.TestCase):
    """Test message trace functionality."""

    def test_add_error_message(self):
        """Response.add_error() adds error to error_stack."""
        response = Response.success(data={})

        response.add_error(
            message="Validation failed",
            code="VALIDATION_ERROR",
            details={"field": "email"},
        )

        self.assertEqual(len(response.error_stack), 1)
        self.assertEqual(response.error_stack[0].message, "Validation failed")
        self.assertEqual(response.error_stack[0].code, "VALIDATION_ERROR")
        self.assertEqual(response.error_stack[0].severity, TraceSeverityLevel.ERROR)
        self.assertFalse(response.is_success)

    def test_add_warning_message(self):
        """Response.add_warning() adds warning to warning_stack."""
        response = Response.success(data={})
        response.add_warning("This is deprecated")

        self.assertEqual(len(response.warning_stack), 1)
        self.assertEqual(response.warning_stack[0].message, "This is deprecated")
        self.assertEqual(response.warning_stack[0].severity, TraceSeverityLevel.WARNING)
        self.assertTrue(response.is_success)  # Warnings don't make response fail

    def test_add_info_message(self):
        """Response.add_info() adds info to info_stack."""
        response = Response.success(data={})
        response.add_info("Operation completed", code="OP_COMPLETE")

        self.assertEqual(len(response.info_stack), 1)
        self.assertEqual(response.info_stack[0].message, "Operation completed")
        self.assertEqual(response.info_stack[0].code, "OP_COMPLETE")
        self.assertEqual(response.info_stack[0].severity, TraceSeverityLevel.INFO)

    def test_message_trace_severity_levels(self):
        """MessageTrace correctly differentiates severity levels."""
        error_trace = MessageTrace(message="Error", severity=TraceSeverityLevel.ERROR)
        warning_trace = MessageTrace(message="Warning", severity=TraceSeverityLevel.WARNING)
        info_trace = MessageTrace(message="Info", severity=TraceSeverityLevel.INFO)

        self.assertEqual(error_trace.severity, TraceSeverityLevel.ERROR)
        self.assertEqual(warning_trace.severity, TraceSeverityLevel.WARNING)
        self.assertEqual(info_trace.severity, TraceSeverityLevel.INFO)


class TestResponseSerialization(unittest.TestCase):
    """Test Response serialization to dict and JSON."""

    def test_response_to_dict(self):
        """response.to_dict() converts Pydantic model to plain dict."""
        response = Response.success(
            data={"name": "doc1", "title": "Test"},
            metadata={"timestamp": "2026-02-16", "sid": "abc"},
        )
        response.add_warning("Test warning")

        response_dict = response.to_dict()

        self.assertIsInstance(response_dict, dict)
        self.assertTrue(response_dict["is_success"])
        self.assertEqual(response_dict["data"], {"name": "doc1", "title": "Test"})
        self.assertEqual(response_dict["metadata"]["timestamp"], "2026-02-16")
        self.assertEqual(len(response_dict["warning_stack"]), 1)

    def test_response_to_json(self):
        """response.to_json() converts to JSON string."""
        response = Response.success(data={"test": "data"})
        json_str = response.to_json()

        self.assertIsInstance(json_str, str)
        # Parse to verify it's valid JSON
        parsed = json.loads(json_str)
        self.assertTrue(parsed["is_success"])
        self.assertEqual(parsed["data"], {"test": "data"})

    def test_response_dict_has_all_fields(self):
        """Serialized response dict includes all fields."""
        response = Response.success(data={"id": 1})
        response.add_error("Test error")
        response.add_warning("Test warning")
        response.add_info("Test info")

        d = response.to_dict()

        self.assertIn("is_success", d)
        self.assertIn("data", d)
        self.assertIn("error_stack", d)
        self.assertIn("warning_stack", d)
        self.assertIn("info_stack", d)
        self.assertIn("metadata", d)


class TestResponseBuilder(unittest.TestCase):
    """Test ResponseBuilder pattern for complex response construction."""

    def test_builder_creates_successful_response(self):
        """ResponseBuilder creates successful response with all fields."""
        response = (
            ResponseBuilder()
            .with_data({"id": 1, "name": "test"})
            .with_metadata({"timestamp": "2026-02-16"})
            .with_info("Operation completed")
            .build()
        )

        self.assertTrue(response.is_success)
        self.assertEqual(response.data, {"id": 1, "name": "test"})
        self.assertEqual(response.metadata["timestamp"], "2026-02-16")
        self.assertEqual(len(response.info_stack), 1)

    def test_builder_creates_failure_response(self):
        """ResponseBuilder creates failure response."""
        response = (
            ResponseBuilder()
            .with_error("Permission denied", code="PERMISSION_DENIED")
            .with_warning("This operation was blocked")
            .build()
        )

        self.assertFalse(response.is_success)
        self.assertEqual(len(response.error_stack), 1)
        self.assertEqual(response.error_stack[0].code, "PERMISSION_DENIED")
        self.assertEqual(len(response.warning_stack), 1)

    def test_builder_chainable(self):
        """ResponseBuilder methods are chainable."""
        response = (
            ResponseBuilder()
            .with_data({"test": "data"})
            .with_error("Error 1")
            .with_error("Error 2")
            .with_warning("Warning 1")
            .with_info("Info 1")
            .build()
        )

        self.assertEqual(len(response.error_stack), 2)
        self.assertEqual(len(response.warning_stack), 1)
        self.assertEqual(len(response.info_stack), 1)


class TestResponseMethods(unittest.TestCase):
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
        self.assertEqual(len(all_messages), 4)
        # Check that we have at least one of each type
        severities = [msg.severity for msg in all_messages]
        self.assertIn(TraceSeverityLevel.ERROR, severities)
        self.assertIn(TraceSeverityLevel.WARNING, severities)
        self.assertIn(TraceSeverityLevel.INFO, severities)

    def test_set_data_returns_self(self):
        """set_data() returns self for chaining."""
        response = Response.success()
        result = response.set_data({"key": "value"})

        self.assertIs(result, response)
        self.assertEqual(response.data, {"key": "value"})

    def test_add_error_returns_self(self):
        """add_error() returns self for chaining."""
        response = Response.success()
        result = response.add_error("Error")

        self.assertIs(result, response)
        self.assertEqual(len(response.error_stack), 1)


class TestResponseFieldValidation(unittest.TestCase):
    """Test Response field validation and type safety."""

    def test_response_with_generic_data_types(self):
        """Response handles various data types."""
        # Dict data
        resp1 = Response.success(data={"key": "value"})
        self.assertIsInstance(resp1.data, dict)

        # List data
        resp2 = Response.success(data=[1, 2, 3])
        self.assertIsInstance(resp2.data, list)

        # String data
        resp3 = Response.success(data="test string")
        self.assertIsInstance(resp3.data, str)

        # None data
        resp4 = Response.success(data=None)
        self.assertIsNone(resp4.data)

    def test_response_metadata_preservation(self):
        """Metadata is preserved through serialization."""
        metadata = {
            "timestamp": "2026-02-16 10:30:00",
            "sid": "socket_123",
            "site": "test_site",
            "custom_field": "custom_value",
        }

        response = Response.success(data={"test": "data"}, metadata=metadata)
        serialized = response.to_dict()

        self.assertEqual(serialized["metadata"], metadata)

    def test_response_error_stack_with_multiple_errors(self):
        """Response can hold multiple errors with different codes."""
        response = Response()  # empty: no default error

        response.add_error("Error 1", code="ERR_001")
        response.add_error("Error 2", code="ERR_002")
        response.add_error("Error 3", code="ERR_003")

        self.assertEqual(len(response.error_stack), 3)
        self.assertEqual(response.error_stack[0].code, "ERR_001")
        self.assertEqual(response.error_stack[1].code, "ERR_002")
        self.assertEqual(response.error_stack[2].code, "ERR_003")
