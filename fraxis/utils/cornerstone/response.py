# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Response Envelope Module

Provides a lightweight, Pydantic-free response envelope for Fraxis Socket.IO operations.
Replaces Pydantic with plain Python dataclasses for simplicity and Socket.IO compatibility.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict
from enum import Enum
from datetime import datetime, date, time
import json


class TraceSeverityLevel(Enum):
    """Severity levels for messages in response stacks."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class MessageTrace:
    """Represents a single message (error, warning, or info) in a response."""
    message: str
    severity: TraceSeverityLevel
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message trace to dictionary."""
        return {
            'code': self.code,
            'message': self.message,
            'severity': self.severity.value,  # Convert enum to string
            'details': self.details,
            'stack_trace': self.stack_trace
        }


@dataclass
class Response:
    """
    Generic response envelope for standardized data and message exchange.
    
    No Pydantic dependency - uses plain Python dataclasses for:
    - Simplicity
    - Socket.IO compatibility
    - Easy serialization
    - No version conflicts
    """
    
    data: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None
    is_success: bool = True
    error_stack: List[MessageTrace] = field(default_factory=list)
    warning_stack: List[MessageTrace] = field(default_factory=list)
    info_stack: List[MessageTrace] = field(default_factory=list)
    
    def __post_init__(self):
        """Auto-calculate is_success based on error_stack."""
        if self.error_stack:
            self.is_success = False
        else:
            self.is_success = True
    
    def add_error(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None
    ) -> 'Response':
        """Add an error message to the response."""
        error_msg = MessageTrace(
            code=code,
            message=message,
            severity=TraceSeverityLevel.ERROR,
            details=details,
            stack_trace=stack_trace
        )
        self.error_stack.append(error_msg)
        self.is_success = False
        return self
    
    def add_warning(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> 'Response':
        """Add a warning message to the response."""
        warning_msg = MessageTrace(
            code=code,
            message=message,
            severity=TraceSeverityLevel.WARNING,
            details=details
        )
        self.warning_stack.append(warning_msg)
        return self
    
    def add_info(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> 'Response':
        """Add an informational message to the response."""
        info_msg = MessageTrace(
            code=code,
            message=message,
            severity=TraceSeverityLevel.INFO,
            details=details
        )
        self.info_stack.append(info_msg)
        return self
    
    def set_data(self, data: Any) -> 'Response':
        """Set the response data."""
        self.data = data
        return self
    
    def get_all_messages(self) -> List[MessageTrace]:
        """Get all messages sorted by severity."""
        all_messages = self.error_stack + self.warning_stack + self.info_stack
        
        # Sort by severity: ERROR > WARNING > INFO
        severity_order = {
            TraceSeverityLevel.ERROR: 3,
            TraceSeverityLevel.WARNING: 2,
            TraceSeverityLevel.INFO: 1
        }
        
        return sorted(
            all_messages,
            key=lambda x: severity_order.get(x.severity, 0),
            reverse=True
        )
    
    def _make_serializable(self, obj: Any) -> Any:
        """Recursively convert non-serializable objects to JSON-compatible types."""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, MessageTrace):
            return obj.to_dict()
        elif hasattr(obj, 'to_dict'):
            # Support objects with to_dict() method (like Frappe Document)
            try:
                return obj.to_dict()
            except Exception:
                return str(obj)
        elif hasattr(obj, '__dict__'):
            # Last resort: convert object attributes to dict
            try:
                return self._make_serializable(obj.__dict__)
            except Exception:
                return str(obj)
        else:
            return obj
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert response to dictionary with proper JSON serialization.
        
        Handles:
        - Enum values (converted to strings)
        - DateTime objects (converted to ISO format)
        - Frappe Document objects (converted to dicts)
        - Any object with to_dict() method
        """
        result = {
            'data': self._make_serializable(self.data),
            'metadata': self._make_serializable(self.metadata),
            'error_stack': [self._make_serializable(e) for e in self.error_stack],
            'warning_stack': [self._make_serializable(w) for w in self.warning_stack],
            'info_stack': [self._make_serializable(i) for i in self.info_stack],
            'is_success': self.is_success
        }
        return result
    
    def to_json(self) -> str:
        """Convert response to JSON string."""
        return json.dumps(self.to_dict(), default=str)
    
    @classmethod
    def success(
        cls,
        data: Any = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> 'Response':
        """Create a successful response."""
        return cls(
            data=data,
            metadata=metadata,
            is_success=True,
            error_stack=[]
        )
    
    @classmethod
    def failure(
        cls,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> 'Response':
        """Create a failed response."""
        response = cls(
            data=None,
            metadata=metadata,
            is_success=False,
            error_stack=[]
        )
        if error:
            response.add_error(error, error_code, details, stack_trace)
        return response
    
    @property
    def has_errors(self) -> bool:
        """Check if response has errors."""
        return len(self.error_stack) > 0
    
    @property
    def has_warnings(self) -> bool:
        """Check if response has warnings."""
        return len(self.warning_stack) > 0
    
    @property
    def has_info(self) -> bool:
        """Check if response has informational messages."""
        return len(self.info_stack) > 0


# Lightweight builder pattern (optional, for complex response construction)
class ResponseBuilder:
    """Builder pattern for creating complex responses."""
    
    def __init__(self):
        """Initialize builder with a new Response."""
        self._response = Response()
    
    def with_data(self, data: Any) -> 'ResponseBuilder':
        """Set response data."""
        self._response.set_data(data)
        return self
    
    def with_metadata(self, metadata: Dict[str, Any]) -> 'ResponseBuilder':
        """Set response metadata."""
        self._response.metadata = metadata
        return self
    
    def with_error(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None
    ) -> 'ResponseBuilder':
        """Add an error message."""
        self._response.add_error(message, code, details, stack_trace)
        return self
    
    def with_warning(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> 'ResponseBuilder':
        """Add a warning message."""
        self._response.add_warning(message, code, details)
        return self
    
    def with_info(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> 'ResponseBuilder':
        """Add an info message."""
        self._response.add_info(message, code, details)
        return self
    
    def build(self) -> Response:
        """Build and return the response."""
        return self._response
