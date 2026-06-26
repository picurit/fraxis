# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""Unit tests for permission-aware broadcast (analysis S3-3, §7.5).

``FraxisNamespace.emit_to_permitted`` must re-check each subscriber's read permission
at emit time and deliver only to permitted users — so a user whose access was revoked
after subscribing stops receiving change events on the next broadcast.

The Socket.IO server, its room manager and the Frappe executor are mocked so the
filtering logic is exercised deterministically with no live server or DB.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from fraxis.fraxis_socket_io.base import FraxisNamespace


class _NS(FraxisNamespace):
    _handler_map = {}


def _make_namespace(participants, sessions):
    ns = _NS("/api/document")

    server = MagicMock()
    server.manager.get_participants = MagicMock(return_value=list(participants))

    async def _get_session(sid, namespace=None):
        return sessions.get(sid)

    server.get_session = _get_session
    ns.server = server

    emitted = []

    async def _emit(event, data=None, to=None, room=None, namespace=None, **kwargs):
        emitted.append({"event": event, "to": to, "namespace": namespace, "data": data})

    ns.emit = _emit
    return ns, emitted


@pytest.mark.unit
class TestEmitToPermitted:
    def test_revoked_user_is_filtered_out(self):
        """userA keeps read access (2 sids), userB is revoked (1 sid) → only A delivered."""
        ns, emitted = _make_namespace(
            participants=[("sidA1", "e1"), ("sidA2", "e2"), ("sidB", "e3")],
            sessions={
                "sidA1": {"user": "a@x"},
                "sidA2": {"user": "a@x"},
                "sidB": {"user": "b@x"},
            },
        )

        async def fake_run_frappe(fn, *args, user=None, **kwargs):
            return user == "a@x"  # only userA may read

        with patch("fraxis.fraxis_socket_io.base.run_frappe", side_effect=fake_run_frappe):
            asyncio.run(
                ns.emit_to_permitted(
                    "document:changed",
                    {"doctype": "ToDo", "name": "X", "action": "update"},
                    doctype="ToDo",
                    room="doctype:ToDo",
                    namespace="/api/doctype",
                )
            )

        targets = sorted(e["to"] for e in emitted)
        assert targets == ["sidA1", "sidA2"]
        assert {e["event"] for e in emitted} == {"document:changed"}
        assert {e["namespace"] for e in emitted} == {"/api/doctype"}

    def test_permission_checked_once_per_distinct_user(self):
        """Two sids of the same user → exactly one permission check, both delivered."""
        ns, emitted = _make_namespace(
            participants=[("s1", "e1"), ("s2", "e2")],
            sessions={"s1": {"user": "a@x"}, "s2": {"user": "a@x"}},
        )
        checked_users = []

        async def fake_run_frappe(fn, *args, user=None, **kwargs):
            checked_users.append(user)
            return True

        with patch("fraxis.fraxis_socket_io.base.run_frappe", side_effect=fake_run_frappe):
            asyncio.run(
                ns.emit_to_permitted(
                    "document:changed", {}, doctype="ToDo", room="r", namespace="/api/doctype"
                )
            )

        assert checked_users == ["a@x"]  # one check, not per-sid
        assert sorted(e["to"] for e in emitted) == ["s1", "s2"]

    def test_no_participants_short_circuits(self):
        """Empty room → no permission checks, no emits (no overhead on hot paths)."""
        ns, emitted = _make_namespace(participants=[], sessions={})

        def boom(*a, **k):
            raise AssertionError("permission must not be checked for an empty room")

        with patch("fraxis.fraxis_socket_io.base.run_frappe", side_effect=boom):
            asyncio.run(
                ns.emit_to_permitted("e", {}, doctype="ToDo", room="r", namespace="/api/doctype")
            )

        assert emitted == []

    def test_guest_and_sessionless_sids_are_skipped(self):
        """Sids with no bound user or the Guest user are never delivered to."""
        ns, emitted = _make_namespace(
            participants=[("guest", "e1"), ("nosession", "e2"), ("real", "e3")],
            sessions={"guest": {"user": "Guest"}, "nosession": None, "real": {"user": "a@x"}},
        )

        async def fake_run_frappe(fn, *args, user=None, **kwargs):
            return True

        with patch("fraxis.fraxis_socket_io.base.run_frappe", side_effect=fake_run_frappe):
            asyncio.run(
                ns.emit_to_permitted("e", {}, doctype="ToDo", room="r", namespace="/api/doctype")
            )

        assert [e["to"] for e in emitted] == ["real"]

    def test_permission_check_exception_does_not_deliver(self):
        """If the permission check errors out, that user is not delivered to (fail-closed)."""
        ns, emitted = _make_namespace(
            participants=[("s1", "e1")],
            sessions={"s1": {"user": "a@x"}},
        )

        async def fake_run_frappe(fn, *args, user=None, **kwargs):
            raise RuntimeError("db down")

        with patch("fraxis.fraxis_socket_io.base.run_frappe", side_effect=fake_run_frappe):
            asyncio.run(
                ns.emit_to_permitted("e", {}, doctype="ToDo", room="r", namespace="/api/doctype")
            )

        assert emitted == []  # gather(return_exceptions=True) → verdict is not True → skipped
