# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Regression tests for the response-envelope hardening (analysis S3-1, S4-6, S2-2)."""

import unittest

from fraxis.utils.cornerstone.response import (
    UNKNOWN_ERROR_CODE,
    MessageTrace,
    Response,
    TraceSeverityLevel,
)


class TestFailureAuthority(unittest.TestCase):
    def test_failure_with_no_error_still_reports_failure(self):
        """S3-1: Response.failure() must never claim success."""
        r = Response.failure()
        self.assertFalse(r.is_success)
        self.assertEqual(len(r.error_stack), 1)
        self.assertEqual(r.error_stack[0].code, UNKNOWN_ERROR_CODE)

    def test_failure_with_falsy_error_still_records(self):
        r = Response.failure(error="")
        self.assertFalse(r.is_success)
        self.assertTrue(r.error_stack)

    def test_success_has_no_error(self):
        r = Response.success(data={"x": 1})
        self.assertTrue(r.is_success)
        self.assertFalse(r.error_stack)


class TestNoStackTraceLeak(unittest.TestCase):
    def test_message_trace_has_no_stack_trace_field(self):
        """S2-2: tracebacks are never part of the client-facing envelope."""
        trace = MessageTrace(message="boom", severity=TraceSeverityLevel.ERROR, code="X")
        d = trace.to_dict()
        self.assertNotIn("stack_trace", d)
        self.assertEqual(set(d.keys()), {"code", "message", "severity", "details"})

    def test_failure_dict_carries_no_stack_trace(self):
        r = Response.failure(error="boom", error_code="X")
        for entry in r.to_dict()["error_stack"]:
            self.assertNotIn("stack_trace", entry)


class TestSerializationCycleGuard(unittest.TestCase):
    def test_self_referential_dict_does_not_recurse(self):
        """S4-6: a reference cycle serializes to a sentinel, not RecursionError."""
        d = {"a": 1}
        d["self"] = d
        r = Response.success(data=d)
        out = r.to_dict()["data"]
        self.assertEqual(out["a"], 1)
        self.assertEqual(out["self"], "<cycle>")

    def test_self_referential_list_does_not_recurse(self):
        lst = [1, 2]
        lst.append(lst)
        r = Response.success(data={"items": lst})
        out = r.to_dict()["data"]["items"]
        self.assertEqual(out[0], 1)
        self.assertEqual(out[2], "<cycle>")

    def test_arbitrary_object_stringified(self):
        class Weird:
            def __init__(self):
                self.secret = "do-not-walk"

        out = Response.success(data={"obj": Weird()}).to_dict()["data"]["obj"]
        self.assertIsInstance(out, str)
