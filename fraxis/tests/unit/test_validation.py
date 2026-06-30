# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for the framework-free validation / room helpers."""

import unittest

from fraxis.services import validation


class TestClampLimit(unittest.TestCase):
    def test_default_on_none(self):
        self.assertEqual(validation.clamp_limit(None), validation.DEFAULT_LIMIT)

    def test_default_on_bad_input(self):
        self.assertEqual(validation.clamp_limit("abc"), validation.DEFAULT_LIMIT)
        self.assertEqual(validation.clamp_limit({}), validation.DEFAULT_LIMIT)

    def test_default_on_nonpositive(self):
        self.assertEqual(validation.clamp_limit(0), validation.DEFAULT_LIMIT)
        self.assertEqual(validation.clamp_limit(-5), validation.DEFAULT_LIMIT)

    def test_passes_through_in_range(self):
        self.assertEqual(validation.clamp_limit(10), 10)
        self.assertEqual(validation.clamp_limit("25"), 25)

    def test_caps_at_maximum(self):
        self.assertEqual(validation.clamp_limit(10_000), validation.MAX_LIMIT)
        self.assertEqual(validation.clamp_limit(validation.MAX_LIMIT + 1), validation.MAX_LIMIT)


class TestRequire(unittest.TestCase):
    def test_passes_when_present(self):
        validation.require({"doctype": "ToDo", "name": "x"}, "doctype", "name")

    def test_raises_when_missing(self):
        with self.assertRaises(ValueError):
            validation.require({"doctype": "ToDo"}, "doctype", "name")

    def test_raises_when_empty(self):
        with self.assertRaises(ValueError):
            validation.require({"doctype": ""}, "doctype")

    def test_raises_on_none_data(self):
        with self.assertRaises(ValueError):
            validation.require(None, "doctype")


class TestRoomBuilders(unittest.TestCase):
    def test_document_room(self):
        self.assertEqual(validation.document_room("ToDo", "abc"), "document:ToDo:abc")

    def test_collection_room(self):
        self.assertEqual(validation.collection_room("ToDo"), "doctype:ToDo")

    def test_method_room(self):
        self.assertEqual(validation.method_room("fraxis.api.x"), "method:fraxis.api.x")

    def test_task_room(self):
        self.assertEqual(validation.task_room("fraxis.api.x", "job1"), "method:fraxis.api.x:job1")


class TestValidateFields(unittest.TestCase):
    """Allowlist of doctype:list ``fields`` against valid columns (analysis §7.3)."""

    allowed = {"name", "description", "status", "modified"}

    def test_none_passes_through(self):
        self.assertIsNone(validation.validate_fields(None, self.allowed))
        self.assertIsNone(validation.validate_fields([], self.allowed))

    def test_allowed_string_and_list(self):
        self.assertEqual(validation.validate_fields("description", self.allowed), ["description"])
        self.assertEqual(
            validation.validate_fields(["name", "status"], self.allowed), ["name", "status"]
        )

    def test_wildcard_allowed(self):
        self.assertEqual(validation.validate_fields("*", self.allowed), ["*"])

    def test_disallowed_column_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_fields(["name", "secret_field"], self.allowed)

    def test_injection_attempt_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_fields(["(SELECT password FROM tabUser)"], self.allowed)

    def test_bad_type_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_fields(123, self.allowed)


class TestValidateOrderBy(unittest.TestCase):
    """Allowlist of doctype:list ``order_by`` (analysis §7.3 / S1-3)."""

    allowed = {"name", "modified", "creation"}

    def test_none_passes_through(self):
        self.assertIsNone(validation.validate_order_by(None, self.allowed))
        self.assertIsNone(validation.validate_order_by("", self.allowed))

    def test_bare_column_defaults_asc(self):
        self.assertEqual(validation.validate_order_by("modified", self.allowed), "modified asc")

    def test_explicit_direction(self):
        self.assertEqual(
            validation.validate_order_by("creation desc", self.allowed), "creation desc"
        )

    def test_multiple_clauses(self):
        self.assertEqual(
            validation.validate_order_by("name asc, modified desc", self.allowed),
            "name asc, modified desc",
        )

    def test_disallowed_column_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_order_by("password desc", self.allowed)

    def test_bad_direction_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_order_by("name sideways", self.allowed)

    def test_injection_clause_raises(self):
        with self.assertRaises(ValueError):
            validation.validate_order_by("name; DROP TABLE tabUser", self.allowed)

    def test_wildcard_rejected_for_order_by(self):
        with self.assertRaises(ValueError):
            validation.validate_order_by("*", self.allowed)


class TestSanitizeError(unittest.TestCase):
    """Tests for error sanitization (analysis NEW-1, S2-2)."""

    def test_value_error_preserves_message(self):
        msg = validation.sanitize_error(ValueError("field is required"))
        self.assertEqual(msg, "field is required")

    def test_type_error_preserves_message(self):
        msg = validation.sanitize_error(TypeError("args must be dict"))
        self.assertEqual(msg, "args must be dict")

    def test_key_error_preserves_message(self):
        msg = validation.sanitize_error(KeyError("missing_key"))
        self.assertIn("missing_key", msg)

    def test_frappe_validation_error_preserves_message(self):
        import frappe

        msg = validation.sanitize_error(frappe.ValidationError("Invalid value"))
        self.assertEqual(msg, "Invalid value")

    def test_frappe_permission_error_preserves_message(self):
        import frappe

        msg = validation.sanitize_error(frappe.PermissionError("No access"))
        self.assertEqual(msg, "No access")

    def test_unknown_exception_generic_message(self):
        msg = validation.sanitize_error(RuntimeError("internal details"))
        self.assertEqual(msg, "RuntimeError: operation failed")

    def test_database_error_generic_message(self):
        msg = validation.sanitize_error(Exception("connection refused on port 5432"))
        self.assertEqual(msg, "Exception: operation failed")

    def test_empty_message_on_safe_type(self):
        import frappe

        msg = validation.sanitize_error(frappe.ValidationError(""))
        self.assertEqual(msg, "ValidationError")
