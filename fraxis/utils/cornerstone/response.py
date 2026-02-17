# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Any, Dict
from pydantic import BaseModel, Field
from enum import Enum

T = TypeVar('T')

class TraceSeverityLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class MessageTrace(BaseModel):
    code: Optional[str] = None
    message: str
    severity: TraceSeverityLevel
    details: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None

class Response(BaseModel, Generic[T]):
    """Generic response model for standardized data and messages exchange."""
    is_success: bool = Field(default=None, description="Indicates if the operation was successful")
    error_stack: List[MessageTrace] = Field(default_factory=list, description="Error messages listed in case of failure")
    info_stack: List[MessageTrace] = Field(default_factory=list, description="Informational messages listed to provide context")
    warning_stack: List[MessageTrace] = Field(default_factory=list, description="Warning messages listed to highlight potential issues")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata related to the response")
    data: Optional[T] = Field(default=None, description="Main payload if available")
    
    class ConfigDict:
        arbitrary_types_allowed = True
        use_enum_values = True
    
    def __init__(self, **kargs: Any):
        super().__init__(**kargs)
        # Auto-calculate is_success based on error_stack
        if not hasattr(self, 'is_success') or self.is_success is None:
            self.is_success = len(self.error_stack) == 0

    def add_error(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None, stack_trace: Optional[str] = None) -> 'Response[T]':
        """Add an error message to the response"""
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
    
    def add_warning(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None) -> 'Response[T]':
        """Add a warning message to the response"""
        warning_msg = MessageTrace(
            code=code,
            message=message,
            severity=TraceSeverityLevel.WARNING,
            details=details
        )
        self.warning_stack.append(warning_msg)
        return self

    def add_info(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None) -> 'Response[T]':
        """Add an informational message to the response"""
        info_msg = MessageTrace(
            code=code,
            message=message,
            severity=TraceSeverityLevel.INFO,
            details=details
        )
        self.info_stack.append(info_msg)
        return self
    
    def set_data(self, data: T) -> 'Response[T]':
        """Set the response data"""
        self.data = data
        return self

    def get_all_messages(self) -> List[MessageTrace]:
        """Get all messages sorted by severity"""
        all_messages = self.error_stack + self.warning_stack + self.info_stack
        return sorted(all_messages, key=lambda x: x.severity.value, reverse=True)
    
    def to_dict(self, *args, **kwargs) -> Dict[str, Any]:
        """Convert response to dictionary, refers to pydantic's model_dump and check docs for args/kwargs"""
        return self.model_dump(*args, **kwargs)
    
    def to_json(self, *args, **kwargs) -> str:
        """Convert response to JSON string, refers to pydantic's model_dump_json and check docs for args/kwargs"""
        return self.model_dump_json(*args, **kwargs)
    
    @classmethod
    def success(cls, data: T = None, metadata: Optional[Dict[str, Any]] = None) -> 'Response[T]':
        """Create a successful response"""
        return cls(is_success=True, data=data, metadata=metadata)

    @classmethod
    def failure(cls, error: str = None, error_code: str = None, details: Optional[Dict[str, Any]] = None, stack_trace: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> 'Response[T]':
        """Create a failed response"""
        response = cls(is_success=False, metadata=metadata)
        if error:
            return response.add_error(error, error_code, details, stack_trace)
        return response
    
    @property
    def has_errors(self) -> bool:
        """Check if response has errors"""
        return len(self.error_stack) > 0
    
    @property
    def has_warnings(self) -> bool:
        """Check if response has warnings"""
        return len(self.warning_stack) > 0
    
    @property
    def has_info(self) -> bool:
        """Check if response has informational messages"""
        return len(self.info_stack) > 0

# Builder Pattern for more complex response construction
class ResponseBuilder(Generic[T]):
    """Builder pattern for creating complex responses"""
    
    def __init__(self):
        self._response = Response[T]()
    
    def with_data(self, data: T) -> 'ResponseBuilder[T]':
        self._response.set_data(data)
        return self

    def with_metadata(self, metadata: Dict[str, Any]) -> 'ResponseBuilder[T]':
        self._response.metadata = metadata
        return self

    def with_error(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None, stack_trace: Optional[str] = None) -> 'ResponseBuilder[T]':
        self._response.add_error(message, code, details, stack_trace)
        return self

    def with_warning(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None) -> 'ResponseBuilder[T]':
        self._response.add_warning(message, code, details)
        return self

    def with_info(self, message: str, code: str = None, details: Optional[Dict[str, Any]] = None) -> 'ResponseBuilder[T]':
        self._response.add_info(message, code, details)
        return self

    def build(self) -> 'Response[T]':
        return self._response

# Interface for response handlers
class ResponseHandler(ABC, Generic[T]):
    @abstractmethod
    def handle(self, response: Response[T]) -> None:
        pass

# TODO: Implement logging response handler
"""
class LoggingResponseHandler(ResponseHandler[T]): 
    def handle(self, response: Response[T]) -> None:
        # Log the response details
        pass
"""
            
# TODO: Create class BaseResponseFactory, and class DefaultResponseFactory(BaseResponseFactory):
"""
class BaseResponseFactory:
    #Base contract for converting domain Response -> transport-specific payloads.
    def to_http(self, response: Response[Any]) -> HTTPResponse:
        raise NotImplementedError

    def to_ws(self, response: Response[Any]) -> WSResponse:
        raise NotImplementedError

    def to_grpc(self, response: Response[Any]) -> GRPCResponse:
        raise NotImplementedError
"""

"""
class DefaultResponseFactory(BaseResponseFactory):
    #Converts Response -> JSON envelope (HTTP), WebSocket event, and placeholder gRPC.

    def __init__(self, status_mapper: Callable[[Response[Any]], int] = default_status_from_response):
        self._status_mapper = status_mapper

    def _envelope(self, resp: Response[Any]) -> Dict[str, Any]:
        pass
"""

