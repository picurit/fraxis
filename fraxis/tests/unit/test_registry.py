# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for the fraxis method registry (framework-free)."""

import unittest

from fraxis import registry


class TestFraxisMethodRegistry(unittest.TestCase):
    def setUp(self):
        registry.clear_registry()

    def tearDown(self):
        registry.clear_registry()

    def test_registers_with_dotted_path_key(self):
        @registry.fraxis_method(execution="async", realtime=True)
        def sample():
            return 1

        key = f"{sample.__module__}.{sample.__qualname__}"
        meta = registry.get_fraxis_method(key)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["execution"], "async")
        self.assertTrue(meta["realtime"])
        self.assertEqual(meta["queue"], "fraxis")

    def test_marks_function_attribute(self):
        @registry.fraxis_method(execution="sync", realtime=False, queue="fraxis")
        def sample():
            return 1

        self.assertEqual(sample.__fraxis_method__["execution"], "sync")
        self.assertFalse(sample.__fraxis_method__["realtime"])

    def test_is_realtime_only_for_registered_realtime(self):
        @registry.fraxis_method(realtime=True)
        def rt():
            return 1

        @registry.fraxis_method(realtime=False)
        def plain():
            return 1

        self.assertTrue(registry.is_realtime(f"{rt.__module__}.{rt.__qualname__}"))
        self.assertFalse(registry.is_realtime(f"{plain.__module__}.{plain.__qualname__}"))
        # Unregistered methods are never realtime.
        self.assertFalse(registry.is_realtime("some.unregistered.method"))

    def test_invalid_execution_mode_rejected(self):
        with self.assertRaises(ValueError):
            registry.fraxis_method(execution="bogus")

    def test_get_unregistered_returns_none(self):
        self.assertIsNone(registry.get_fraxis_method("not.registered"))
        self.assertFalse(registry.is_registered("not.registered"))
