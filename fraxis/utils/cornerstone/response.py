# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Response Envelope Module

A lightweight, Pydantic-free response envelope for Fraxis Socket.IO operations.

Security note: this envelope carries NO server traceback. Stack traces are logged
server-side (frappe.log_error) and never forwarded to untrusted clients (analysis S2-2).
Failures always carry an error so ``is_success`` cannot lie (analysis S3-1).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional

import json

UNKNOWN_ERROR_MESSAGE = "Unknown error"
UNKNOWN_ERROR_CODE = "UNKNOWN_ERROR"


class TraceSeverityLevel(Enum):
    """Severity levels for messages in response stacks."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class MessageTrace:
    """A single message (error, warning, or info) in a response.

    Deliberately has no ``stack_trace`` field — tracebacks are not client-facing.
    """
    message: str
    severity: TraceSeverityLevel
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "details": self.details,
        }


@dataclass
class Response:
    """Generic response envelope for standardized data and message exchange."""

    data: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None
    is_success: bool = True
    error_stack: List[MessageTrace] = field(default_factory=list)
    warning_stack: List[MessageTrace] = field(default_factory=list)
    info_stack: List[MessageTrace] = field(default_factory=list)

    def __post_init__(self):
        # The presence of an error is the single source of truth for success.
        self.is_success = not self.error_stack

    def add_error(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "Response":
        self.error_stack.append(
            MessageTrace(
                code=code,
                message=message,
                severity=TraceSeverityLevel.ERROR,
                details=details,
            )
        )
        self.is_success = False
        return self

    def add_warning(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "Response":
        self.warning_stack.append(
            MessageTrace(
                code=code,
                message=message,
                severity=TraceSeverityLevel.WARNING,
                details=details,
            )
        )
        return self

    def add_info(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "Response":
        self.info_stack.append(
            MessageTrace(
                code=code,
                message=message,
                severity=TraceSeverityLevel.INFO,
                details=details,
            )
        )
        return self

    def set_data(self, data: Any) -> "Response":
        self.data = data
        return self

    def get_all_messages(self) -> List[MessageTrace]:
        all_messages = self.error_stack + self.warning_stack + self.info_stack
        severity_order = {
            TraceSeverityLevel.ERROR: 3,
            TraceSeverityLevel.WARNING: 2,
            TraceSeverityLevel.INFO: 1,
        }
        return sorted(
            all_messages,
            key=lambda x: severity_order.get(x.severity, 0),
            reverse=True,
        )

    def _make_serializable(self, obj: Any, _seen: Optional[set] = None) -> Any:
        """Recursively convert to JSON-compatible types with a cycle guard (S4-6)."""
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        if isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, MessageTrace):
            return obj.to_dict()

        # Reference cycle protection for containers / arbitrary objects.
        if _seen is None:
            _seen = set()
        obj_id = id(obj)
        if obj_id in _seen:
            return "<cycle>"

        if isinstance(obj, dict):
            _seen.add(obj_id)
            try:
                return {k: self._make_serializable(v, _seen) for k, v in obj.items()}
            finally:
                _seen.discard(obj_id)
        if isinstance(obj, (list, tuple, set)):
            _seen.add(obj_id)
            try:
                return [self._make_serializable(item, _seen) for item in obj]
            finally:
                _seen.discard(obj_id)
        if hasattr(obj, "as_dict"):
            try:
                return self._make_serializable(obj.as_dict(), _seen)
            except Exception:
                return str(obj)
        if hasattr(obj, "to_dict"):
            try:
                return self._make_serializable(obj.to_dict(), _seen)
            except Exception:
                return str(obj)
        # Conservative fallback: do not walk arbitrary __dict__ graphs (over-disclosure /
        # recursion risk); stringify instead.
        return str(obj)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data": self._make_serializable(self.data),
            "metadata": self._make_serializable(self.metadata),
            "error_stack": [self._make_serializable(e) for e in self.error_stack],
            "warning_stack": [self._make_serializable(w) for w in self.warning_stack],
            "info_stack": [self._make_serializable(i) for i in self.info_stack],
            "is_success": self.is_success,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def success(
        cls,
        data: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Response":
        return cls(data=data, metadata=metadata, is_success=True, error_stack=[])

    @classmethod
    def failure(
        cls,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Response":
        """Create a failed response. Always records an error so ``is_success`` is False."""
        response = cls(data=None, metadata=metadata, is_success=False, error_stack=[])
        response.add_error(
            error or UNKNOWN_ERROR_MESSAGE,
            error_code or UNKNOWN_ERROR_CODE,
            details,
        )
        return response

    @property
    def has_errors(self) -> bool:
        return len(self.error_stack) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warning_stack) > 0

    @property
    def has_info(self) -> bool:
        return len(self.info_stack) > 0


class ResponseBuilder:
    """Builder pattern for creating complex responses."""

    def __init__(self):
        self._response = Response()

    def with_data(self, data: Any) -> "ResponseBuilder":
        self._response.set_data(data)
        return self

    def with_metadata(self, metadata: Dict[str, Any]) -> "ResponseBuilder":
        self._response.metadata = metadata
        return self

    def with_error(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ResponseBuilder":
        self._response.add_error(message, code, details)
        return self

    def with_warning(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ResponseBuilder":
        self._response.add_warning(message, code, details)
        return self

    def with_info(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ResponseBuilder":
        self._response.add_info(message, code, details)
        return self

    def build(self) -> Response:
        return self._response
