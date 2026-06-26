# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for the framework-free validation / room helpers."""

import pytest

from fraxis.services import validation


@pytest.mark.unit
class TestClampLimit:
    def test_default_on_none(self):
        assert validation.clamp_limit(None) == validation.DEFAULT_LIMIT

    def test_default_on_bad_input(self):
        assert validation.clamp_limit("abc") == validation.DEFAULT_LIMIT
        assert validation.clamp_limit({}) == validation.DEFAULT_LIMIT

    def test_default_on_nonpositive(self):
        assert validation.clamp_limit(0) == validation.DEFAULT_LIMIT
        assert validation.clamp_limit(-5) == validation.DEFAULT_LIMIT

    def test_passes_through_in_range(self):
        assert validation.clamp_limit(10) == 10
        assert validation.clamp_limit("25") == 25

    def test_caps_at_maximum(self):
        assert validation.clamp_limit(10_000) == validation.MAX_LIMIT
        assert validation.clamp_limit(validation.MAX_LIMIT + 1) == validation.MAX_LIMIT


@pytest.mark.unit
class TestRequire:
    def test_passes_when_present(self):
        validation.require({"doctype": "ToDo", "name": "x"}, "doctype", "name")

    def test_raises_when_missing(self):
        with pytest.raises(ValueError):
            validation.require({"doctype": "ToDo"}, "doctype", "name")

    def test_raises_when_empty(self):
        with pytest.raises(ValueError):
            validation.require({"doctype": ""}, "doctype")

    def test_raises_on_none_data(self):
        with pytest.raises(ValueError):
            validation.require(None, "doctype")


@pytest.mark.unit
class TestRoomBuilders:
    def test_document_room(self):
        assert validation.document_room("ToDo", "abc") == "document:ToDo:abc"

    def test_collection_room(self):
        assert validation.collection_room("ToDo") == "doctype:ToDo"

    def test_method_room(self):
        assert validation.method_room("fraxis.api.x") == "method:fraxis.api.x"

    def test_task_room(self):
        assert validation.task_room("fraxis.api.x", "job1") == "method:fraxis.api.x:job1"


@pytest.mark.unit
class TestValidateFields:
    """Allowlist of doctype:list ``fields`` against valid columns (analysis §7.3)."""

    allowed = {"name", "description", "status", "modified"}

    def test_none_passes_through(self):
        assert validation.validate_fields(None, self.allowed) is None
        assert validation.validate_fields([], self.allowed) is None

    def test_allowed_string_and_list(self):
        assert validation.validate_fields("description", self.allowed) == ["description"]
        assert validation.validate_fields(["name", "status"], self.allowed) == ["name", "status"]

    def test_wildcard_allowed(self):
        assert validation.validate_fields("*", self.allowed) == ["*"]

    def test_disallowed_column_raises(self):
        with pytest.raises(ValueError):
            validation.validate_fields(["name", "secret_field"], self.allowed)

    def test_injection_attempt_raises(self):
        with pytest.raises(ValueError):
            validation.validate_fields(["(SELECT password FROM tabUser)"], self.allowed)

    def test_bad_type_raises(self):
        with pytest.raises(ValueError):
            validation.validate_fields(123, self.allowed)


@pytest.mark.unit
class TestValidateOrderBy:
    """Allowlist of doctype:list ``order_by`` (analysis §7.3 / S1-3)."""

    allowed = {"name", "modified", "creation"}

    def test_none_passes_through(self):
        assert validation.validate_order_by(None, self.allowed) is None
        assert validation.validate_order_by("", self.allowed) is None

    def test_bare_column_defaults_asc(self):
        assert validation.validate_order_by("modified", self.allowed) == "modified asc"

    def test_explicit_direction(self):
        assert validation.validate_order_by("creation desc", self.allowed) == "creation desc"

    def test_multiple_clauses(self):
        assert validation.validate_order_by("name asc, modified desc", self.allowed) == \
            "name asc, modified desc"

    def test_disallowed_column_raises(self):
        with pytest.raises(ValueError):
            validation.validate_order_by("password desc", self.allowed)

    def test_bad_direction_raises(self):
        with pytest.raises(ValueError):
            validation.validate_order_by("name sideways", self.allowed)

    def test_injection_clause_raises(self):
        with pytest.raises(ValueError):
            validation.validate_order_by("name; DROP TABLE tabUser", self.allowed)

    def test_wildcard_rejected_for_order_by(self):
        with pytest.raises(ValueError):
            validation.validate_order_by("*", self.allowed)


@pytest.mark.unit
class TestSanitizeError:
    """Tests for error sanitization (analysis NEW-1, S2-2)."""

    def test_value_error_preserves_message(self):
        msg = validation.sanitize_error(ValueError("field is required"))
        assert msg == "field is required"

    def test_type_error_preserves_message(self):
        msg = validation.sanitize_error(TypeError("args must be dict"))
        assert msg == "args must be dict"

    def test_key_error_preserves_message(self):
        msg = validation.sanitize_error(KeyError("missing_key"))
        assert "missing_key" in msg

    def test_frappe_validation_error_preserves_message(self):
        import frappe
        msg = validation.sanitize_error(frappe.ValidationError("Invalid value"))
        assert msg == "Invalid value"

    def test_frappe_permission_error_preserves_message(self):
        import frappe
        msg = validation.sanitize_error(frappe.PermissionError("No access"))
        assert msg == "No access"

    def test_unknown_exception_generic_message(self):
        msg = validation.sanitize_error(RuntimeError("internal details"))
        assert msg == "RuntimeError: operation failed"

    def test_database_error_generic_message(self):
        msg = validation.sanitize_error(Exception("connection refused on port 5432"))
        assert msg == "Exception: operation failed"

    def test_empty_message_on_safe_type(self):
        import frappe
        msg = validation.sanitize_error(frappe.ValidationError(""))
        assert msg == "ValidationError"
