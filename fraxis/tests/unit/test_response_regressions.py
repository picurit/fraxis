# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Regression tests for the response-envelope hardening (analysis S3-1, S4-6, S2-2)."""

import pytest

from fraxis.utils.cornerstone.response import (
    UNKNOWN_ERROR_CODE,
    MessageTrace,
    Response,
    TraceSeverityLevel,
)


@pytest.mark.unit
class TestFailureAuthority:
    def test_failure_with_no_error_still_reports_failure(self):
        """S3-1: Response.failure() must never claim success."""
        r = Response.failure()
        assert r.is_success is False
        assert len(r.error_stack) == 1
        assert r.error_stack[0].code == UNKNOWN_ERROR_CODE

    def test_failure_with_falsy_error_still_records(self):
        r = Response.failure(error="")
        assert r.is_success is False
        assert r.error_stack

    def test_success_has_no_error(self):
        r = Response.success(data={"x": 1})
        assert r.is_success is True
        assert not r.error_stack


@pytest.mark.unit
class TestNoStackTraceLeak:
    def test_message_trace_has_no_stack_trace_field(self):
        """S2-2: tracebacks are never part of the client-facing envelope."""
        trace = MessageTrace(message="boom", severity=TraceSeverityLevel.ERROR, code="X")
        d = trace.to_dict()
        assert "stack_trace" not in d
        assert set(d.keys()) == {"code", "message", "severity", "details"}

    def test_failure_dict_carries_no_stack_trace(self):
        r = Response.failure(error="boom", error_code="X")
        for entry in r.to_dict()["error_stack"]:
            assert "stack_trace" not in entry


@pytest.mark.unit
class TestSerializationCycleGuard:
    def test_self_referential_dict_does_not_recurse(self):
        """S4-6: a reference cycle serializes to a sentinel, not RecursionError."""
        d = {"a": 1}
        d["self"] = d
        r = Response.success(data=d)
        out = r.to_dict()["data"]
        assert out["a"] == 1
        assert out["self"] == "<cycle>"

    def test_self_referential_list_does_not_recurse(self):
        lst = [1, 2]
        lst.append(lst)
        r = Response.success(data={"items": lst})
        out = r.to_dict()["data"]["items"]
        assert out[0] == 1
        assert out[2] == "<cycle>"

    def test_arbitrary_object_stringified(self):
        class Weird:
            def __init__(self):
                self.secret = "do-not-walk"

        out = Response.success(data={"obj": Weird()}).to_dict()["data"]["obj"]
        assert isinstance(out, str)
