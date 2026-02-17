# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

import click
import frappe
from frappe.commands import get_site, pass_context
import asyncio
import uvicorn
import uvloop
from socketio import AsyncServer, ASGIApp

from fraxis.fraxis_socket_io.base import FraxisNamespace
from fraxis.fraxis_socket_io.namespaces import SystemNamespace
from fraxis.fraxis_socket_io.namespaces.document import DocumentNamespace
from fraxis.fraxis_socket_io.namespaces.doctype import DoctypeNamespace
from fraxis.fraxis_socket_io.namespaces.method import MethodNamespace


class SocketIOServer:
    """
    Manages the Fraxis Socket.IO server.
    
    Runs as a separate process (started via `bench socketio-server`) on a configurable 
    host/port (default `0.0.0.0:8005`), independent of Frappe's gunicorn workers.
    """

    def __init__(self, host: str = '0.0.0.0', port: int = 8005, logging: str = "info"):
        self.host = host
        self.port = port
        self.logging = logging
        
        # Initialize ASGI Socket.IO server
        # - async_mode='asgi': ASGI compatible mode
        # - cors_allowed_origins='*': Allow all origins
        # - async_handlers=True: Handlers are coroutines
        self.sio = AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',
            async_handlers=True,
            logger=False,
            engineio_logger=False,
        )
        
        # Create ASGI application wrapper
        self.app = ASGIApp(self.sio)
        
        # Register all namespaces
        self._register_namespaces()
    
    def _register_namespaces(self):
        """
        Register all Fraxis namespaces following the specification.
        
        Namespaces:
        - /system: Connection lifecycle, health checks, diagnostics
        - /api/document: Full CRUD on individual Frappe documents
        - /api/doctype: Collection-level operations on a DocType
        - /api/method: Execute whitelisted Frappe methods
        """
        self.sio.register_namespace(SystemNamespace('/system'))
        self.sio.register_namespace(DocumentNamespace('/api/document'))
        self.sio.register_namespace(DoctypeNamespace('/api/doctype'))
        self.sio.register_namespace(MethodNamespace('/api/method'))
    
    async def _serve_uvicorn(self):
        """Coroutine to run the uvicorn server within the uvloop event loop."""
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level=self.logging,
            loop="asyncio"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    def run(self):
        """
        Start the Socket.IO server with uvloop.
        
        The server will listen on the configured host:port and handle:
        - Socket.IO protocol negotiation
        - Namespace routing
        - Event handler dispatch via decorator registry
        - ACK packet generation from handler return values
        """
        frappe.logger("socketio_server").info(
            f"Starting ASGI Socket.IO server on {self.host}:{self.port}"
        )
        
        try:
            # Start uvicorn server with uvloop for high performance
            uvloop.run(self._serve_uvicorn())
        except Exception as e:
            frappe.log_error(title="Socket.IO server error", message=f"Error: {str(e)}")
            raise


class SocketIOManager:
    """Manager class for Socket.IO commands."""

    @staticmethod
    def get_commands():
        """Return the list of Socket.IO related commands."""
        return SocketIOManager._create_commands()
    
    @staticmethod
    def _create_commands():
        """Create and return the socketio-server command."""
        
        @click.command("socketio-server")
        @click.option('--port', default=8005, help='Port to run socketio server on')
        @click.option('--host', default='0.0.0.0', help='Host to bind to')
        @pass_context
        def start_socketio_server(context, port, host):
            """
            Start Fraxis Socket.IO server for bidirectional communication using ASGI.
            
            The server provides:
            - Full CRUD operations on Frappe documents via /api/document namespace
            - Collection-level DocType operations via /api/doctype namespace
            - Whitelisted method execution via /api/method namespace
            - System health and connection management via /system namespace
            
            All communication uses the ACK + State Events dual pattern for request/response
            semantics with automatic correlation and side-effect visibility.
            """
            site = get_site(context)
            frappe.init(site=site)
            frappe.connect()
            
            frappe.logger("socketio_server").info(f"Starting server for site {site}")
            
            try:
                logging_level = "info"
                server = SocketIOServer(host=host, port=port, logging=logging_level)
                server.run()
            except Exception as e:
                frappe.log_error(f"Socket.IO server error: {str(e)}")
            finally:
                frappe.destroy()
        
        return [start_socketio_server]
