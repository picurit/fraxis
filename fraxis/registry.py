# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Fraxis method registry.

Plain ``@frappe.whitelist()`` membership must NOT grant realtime treatment. A method is
realtime-capable only if it is explicitly registered with :func:`fraxis_method`. This
makes "who may receive progress" an auditable, intentional decision instead of an
emergent property of a function signature (analysis §5b).

The registry is framework-light and unit-testable on its own — it holds pure data and a
dotted-path lookup, with no Frappe context required.
"""

import threading
from typing import Any, Callable, Optional

# Execution modes for the dual model (analysis §5c).
EXECUTION_ASYNC = "async"  # invoked via method:execute, runs on the event loop
EXECUTION_SYNC = "sync"    # invoked via method:enqueue, runs in a fraxis RQ worker

_FRAXIS_METHODS: dict[str, dict] = {}
_lock = threading.Lock()


def fraxis_method(
    *,
    execution: str = EXECUTION_ASYNC,
    realtime: bool = True,
    queue: str = "fraxis",
) -> Callable:
    """Register a method as explicitly executable through fraxis.

    :param execution: ``"async"`` → ``method:execute`` on the loop; ``"sync"`` →
        ``method:enqueue`` on the dedicated ``fraxis`` worker.
    :param realtime: ``True`` may receive ``*:progress`` events (callback injected for
        async methods / generator values streamed / ``publish_progress`` honoured in
        workers). ``False`` emits start + end lifecycle events only.
    :param queue: RQ queue used when ``execution="sync"``.
    """
    if execution not in (EXECUTION_ASYNC, EXECUTION_SYNC):
        raise ValueError(f"Invalid execution mode: {execution!r}")

    def deco(fn: Callable) -> Callable:
        key = f"{fn.__module__}.{fn.__qualname__}"
        meta = {"fn": fn, "execution": execution, "realtime": bool(realtime), "queue": queue}
        with _lock:
            _FRAXIS_METHODS[key] = meta
        fn.__fraxis_method__ = {k: v for k, v in meta.items() if k != "fn"}
        return fn

    return deco


def get_fraxis_method(dotted_path: str) -> Optional[dict]:
    """Return the registry entry for a dotted path, or ``None`` if not registered."""
    return _FRAXIS_METHODS.get(dotted_path)


def is_registered(dotted_path: str) -> bool:
    return dotted_path in _FRAXIS_METHODS


def is_realtime(dotted_path: str) -> bool:
    """True only when the method is registered AND flagged realtime."""
    meta = _FRAXIS_METHODS.get(dotted_path)
    return bool(meta and meta.get("realtime"))


def clear_registry() -> None:
    """Test helper: empty the registry."""
    with _lock:
        _FRAXIS_METHODS.clear()
