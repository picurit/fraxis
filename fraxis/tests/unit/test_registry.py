# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for the fraxis method registry (framework-free)."""

import pytest

from fraxis import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear_registry()
    yield
    registry.clear_registry()


@pytest.mark.unit
class TestFraxisMethodRegistry:
    def test_registers_with_dotted_path_key(self):
        @registry.fraxis_method(execution="async", realtime=True)
        def sample():
            return 1

        key = f"{sample.__module__}.{sample.__qualname__}"
        meta = registry.get_fraxis_method(key)
        assert meta is not None
        assert meta["execution"] == "async"
        assert meta["realtime"] is True
        assert meta["queue"] == "fraxis"

    def test_marks_function_attribute(self):
        @registry.fraxis_method(execution="sync", realtime=False, queue="fraxis")
        def sample():
            return 1

        assert sample.__fraxis_method__["execution"] == "sync"
        assert sample.__fraxis_method__["realtime"] is False

    def test_is_realtime_only_for_registered_realtime(self):
        @registry.fraxis_method(realtime=True)
        def rt():
            return 1

        @registry.fraxis_method(realtime=False)
        def plain():
            return 1

        assert registry.is_realtime(f"{rt.__module__}.{rt.__qualname__}") is True
        assert registry.is_realtime(f"{plain.__module__}.{plain.__qualname__}") is False
        # Unregistered methods are never realtime.
        assert registry.is_realtime("some.unregistered.method") is False

    def test_invalid_execution_mode_rejected(self):
        with pytest.raises(ValueError):
            registry.fraxis_method(execution="bogus")

    def test_get_unregistered_returns_none(self):
        assert registry.get_fraxis_method("not.registered") is None
        assert registry.is_registered("not.registered") is False
