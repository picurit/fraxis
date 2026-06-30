# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for the fraxis queue router fallback (framework-light)."""

import unittest
from unittest import mock

from fraxis.runtime import queue_router


class TestQueueRouterFallback(unittest.TestCase):
    def setUp(self):
        queue_router._reset_cache()

    def tearDown(self):
        queue_router._reset_cache()

    def test_default_queue_passes_through_without_probe(self):
        # The fallback queue itself must never probe (it is always assumed available).
        with mock.patch.object(queue_router, "_has_live_worker") as probe:
            self.assertEqual(queue_router.resolve_queue("default"), "default")
            probe.assert_not_called()

    def test_uses_requested_queue_when_worker_is_live(self):
        with mock.patch.object(queue_router, "_has_live_worker", return_value=True) as probe:
            self.assertEqual(queue_router.resolve_queue("fraxis"), "fraxis")
            probe.assert_called_once_with("fraxis")

    def test_falls_back_to_default_when_no_live_worker(self):
        with mock.patch.object(queue_router, "_has_live_worker", return_value=False):
            self.assertEqual(queue_router.resolve_queue("fraxis"), "default")

    def test_decision_is_cached_after_first_resolve(self):
        with mock.patch.object(queue_router, "_has_live_worker", return_value=False) as probe:
            queue_router.resolve_queue("fraxis")
            queue_router.resolve_queue("fraxis")
            probe.assert_called_once()  # probed once, then served from cache

    def test_probe_treats_errors_as_unavailable(self):
        # get_queue raising (e.g. queue not configured / redis down) => unavailable.
        with mock.patch(
            "frappe.utils.background_jobs.get_queue", side_effect=Exception("not configured")
        ):
            self.assertFalse(queue_router._has_live_worker("fraxis"))

    def test_probe_requires_at_least_one_worker(self):
        with mock.patch("frappe.utils.background_jobs.get_queue", return_value=object()), mock.patch(
            "frappe.utils.background_jobs.get_workers", return_value=[]
        ):
            self.assertFalse(queue_router._has_live_worker("fraxis"))

        queue_router._reset_cache()

        with mock.patch("frappe.utils.background_jobs.get_queue", return_value=object()), mock.patch(
            "frappe.utils.background_jobs.get_workers", return_value=[object()]
        ):
            self.assertTrue(queue_router._has_live_worker("fraxis"))

    def test_validate_startup_queue_returns_effective_queue(self):
        logger = mock.Mock()
        with mock.patch.object(queue_router, "_has_live_worker", return_value=False), mock.patch(
            "frappe.logger", return_value=logger
        ):
            self.assertEqual(queue_router.validate_startup_queue("fraxis"), "default")
            logger.warning.assert_called_once()

        queue_router._reset_cache()

        with mock.patch.object(queue_router, "_has_live_worker", return_value=True), mock.patch(
            "frappe.logger", return_value=logger
        ):
            self.assertEqual(queue_router.validate_startup_queue("fraxis"), "fraxis")
            logger.info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
