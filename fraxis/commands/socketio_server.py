import click
import frappe
from frappe.commands import get_site, pass_context
from frappe.utils import get_site_name, now as frappe_now
import asyncio
import uvicorn
import uvloop
from socketio.exceptions import ConnectionRefusedError
from socketio import AsyncNamespace, AsyncServer, ASGIApp
from typing import Dict, Callable, Any, List
from json import dumps, loads

# TODO: remove this import, only for type hinting
import werkzeug.wrappers

from fraxis.utils.cornerstone.response import Response
from fraxis.utils.types import DotDict

class SocketIONamespace(AsyncNamespace):
    """Base namespace with common functionality"""
    
    def validate_auth(self, client_auth) -> bool:
        """Validate client authentication"""
        print(f"Validating client auth, client_auth: {client_auth}")
        # TODO: Implement authentication logic here
        return True
    
    async def on_connect(self, sid, environ, client_auth):
        """Handle client connection"""
        print(f"Client connected, sid: {sid}, environ: {environ}, client_auth: {client_auth}")
        await self.emit('connect:admit', to=sid)
        if not self.validate_auth(client_auth):
            await self.emit('connect:failure', to=sid)
            raise ConnectionRefusedError("Authentication failed")
        else:
            await self.emit('connect:success', to=sid)
        await self.emit('connect:ready', to=sid)
    
    async def on_disconnect(self, sid, reason):
        """Handle client disconnection"""
        print(f"Client disconnected, sid: {sid}, reason: {reason}")
    
    async def on_message(self, sid, data):
        """Handle generic message from client"""
        print(f"Message received, sid: {sid}, data: {data}")

class SystemNamespace(SocketIONamespace):
    """Handle system-level events"""
    
    async def on_ping(self, sid, data: Dict = {}) -> Response:
        """Handle ping event from client"""        
        print(f"Ping received, sid: {sid}, data: {data}")
        await self.emit('ping:admit', to=sid)
        
        data_response = DotDict(data)
        data_response.message = 'pong'
        
        metadata = DotDict()
        metadata.timestamp = frappe_now()
        metadata.sid = sid
        metadata.site = get_site_name(frappe.local.site)

        response = Response.success(
            data=data_response.as_dict(),
            metadata=metadata.as_dict(),
        )

        response_dict = response.to_dict()
        if response.is_success:
            await self.emit('ping:success', response_dict, to=sid)
        else:
            await self.emit('ping:failure', response_dict, to=sid)
        
        await self.emit('ping:end', to=sid)
        
        return response_dict
    
    async def on_health(self, sid, data: Dict = {}) -> Response:
        """Handle health check event from client"""
        print(f"Health check received, sid: {sid}, data: {data}")

        data_response = DotDict()
        data_response.status = 'healthy'

        metadata = DotDict()
        metadata.timestamp = frappe_now()
        metadata.sid = sid
        metadata.site = get_site_name(frappe.local.site)

        response = Response.success(
            data=data_response.as_dict(),
            metadata=metadata.as_dict(),
        ).to_dict()

        await self.emit('health_response', response, to=sid)
        
        return response
    
class APINamespace(SocketIONamespace):
    """Handle frappe API related events"""
    
    async def on_method(self, sid, data) -> Response:
        """Handle method call from client"""
        print(f"Method call received, sid: {sid}, data: {data}")
        await self.emit('method:admit', to=sid)
        
        """
        data expected format:
        {
            "method": "frappe.client.get_list",
            "args": {...}
        }
        """
        
        #call frappe method here and get result
        method = data.get('method')
        args = data.get('args', {})
        # agentbuilder.api.dialogueresponse() argument after ** must be a mapping, not str
        if not isinstance(args, Dict):
            args = loads(args)
        
        current_user = frappe.session.user
        try:
            # TODO: make better method resolution
            frappe.set_user("Administrator")
            method_func = frappe.get_attr(method)
            if asyncio.iscoroutinefunction(method_func):
                result: werkzeug.wrappers.Response = await method_func(**args)
            else:
                result: werkzeug.wrappers.Response = method_func(**args)
            
            data_response = loads(result.get_data(as_text=True))
            
            response = Response.success(
                data=data_response,
                metadata={
                    'timestamp': frappe_now(),
                    'sid': sid,
                    'site': get_site_name(frappe.local.site)
                }
            )

            frappe.db.commit()
            await self.emit('method:success', response.to_dict(), to=sid)
        except Exception as e:
            response = Response.failure(
                error=str(e),
                metadata={
                    'timestamp': frappe_now(),
                    'sid': sid,
                    'site': get_site_name(frappe.local.site)
                }
            )
            await self.emit('method:failure', response.to_dict(), to=sid)

        finally:
            frappe.set_user(current_user)
            await self.emit('method:end', to=sid)
        
        return response.to_dict()

class SocketIOServer:
    """Class to manage the Socket.IO server"""

    def __init__(self, host='0.0.0.0', port=8005, logging="info"):
        self.host = host
        self.port = port
        self.logging = logging
        
        # Initialize ASGI Socket.IO server
        self.sio = AsyncServer(
            async_mode='asgi', 
            cors_allowed_origins='*',
            async_handlers=True,
        )
        self.app = ASGIApp(self.sio)
        
        self._register_namespaces()
    
    def _register_namespaces(self):
        """Register namespaces and their handlers"""
        self.sio.register_namespace(SystemNamespace('/system'))
        self.sio.register_namespace(APINamespace('/api'))
    
    async def doc_create(self, sid, data):
        """Create a new document in any DocType"""
        try:
            print(f"Document creation request from {sid}: {data}")
            # Run synchronous Frappe operations in thread pool
            """
            result = await asyncio.get_event_loop().run_in_executor(
                None, 
                _create_document,
                data
            )
            """
            # Make the call directly synchronous for simplicity
            #result = _create_document(data)
            doc = frappe.new_doc('ToDo')
            doc.update({'description': "Test ToDo from SocketIO"})
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            result = {'doctype': 'ToDo', 'name': doc.name}
            
            await self.sio.emit('doc_created', {
                'success': True,
                'result': result
            }, room=sid)
            
        except Exception as e:
            await self.sio.emit('error', {
                'success': False,
                'error': str(e)
            }, room=sid)
        
    def _create_document(data):
        """Synchronous document creation"""
        doctype = data.get('doctype')
        field_data = data.get('data', {})
        
        doc = frappe.new_doc(doctype)
        doc.update(field_data)
        doc.insert(ignore_permissions=True)
        
        return {'doctype': doctype, 'name': doc.name}
    
    async def _serve_uvicorn(self):
        """Coroutine to run the uvicorn server within the uvloop"""
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
        """Start the Socket.IO server"""
        print(f"Starting ASGI Socket.IO server on {self.host}:{self.port}")
        
        try:
            # Start uvicorn server with uvloop
            uvloop.run(self._serve_uvicorn())
        except Exception as e:
            frappe.log_error(title="Socket.IO server error", message=f"Error: {str(e)}")
            raise

class SocketIOManager:
    """Class to manage Socket.IO commands"""

    @staticmethod
    def get_commands():
        """Return the list of Socket.IO related commands"""
        return SocketIOManager._create_commands()
    
    @staticmethod
    def _create_commands():
        """Crear y retornar el comando socketio-server"""
        
        @click.command("socketio-server")
        @click.option('--port', default=8005, help='Port to run socketio server on')
        @click.option('--host', default='0.0.0.0', help='Host to bind to')
        @pass_context
        def start_socketio_server(context, port, host):
            """Start custom Socket.IO server for bidirectional communication using ASGI"""
            site = get_site(context)
            frappe.init(site=site)
            frappe.connect()
            
            print(f"Starting server for site {site}")
            
            try:
                logging = "info"
                server = SocketIOServer(host=host, port=port, logging=logging)
                server.run()
            except Exception as e:
                frappe.log_error(f"Socket.IO server error: {str(e)}")
            finally:
                frappe.destroy()
        
        return [
            start_socketio_server,
        ]
