import click
import frappe
from frappe.commands import get_site, pass_context
from frappe.utils import get_site_name, now as frappe_now
import asyncio
import uvicorn
import uvloop
import socketio
from typing import Dict, Callable, Any, List

from fraxis.utils.cornerstone.response import Response

class SocketIOServer:
    """Class to manage the Socket.IO server"""

    def __init__(self, host='0.0.0.0', port=8005, logging="info"):
        self.host = host
        self.port = port
        self.logging = logging
        
        # Initialize ASGI Socket.IO server
        self.sio = socketio.AsyncServer(
            async_mode='asgi', 
            cors_allowed_origins='*',
            async_handlers=True,
        )
        self.app = socketio.ASGIApp(self.sio)
        
        #Register events
        self._event_handlers: Dict[str, Callable] = {}
        self._mapping_event_handlers()
        self._bind_event_to_socketio()
    
    def _mapping_event_handlers(self):
        """Map event names to handler methods"""
        self._event_handlers = {
            'connect': self._handle_connect,
            'disconnect': self._handle_disconnect,
            'message': self._handle_message,
            'ping': self._handle_ping,
        }
    
    def _bind_event_to_socketio(self):
        """Bind event handlers to Socket.IO events"""
        for event_name, handler in self._event_handlers.items():
            self.sio.on(event=event_name, handler=handler)
    
    # Event Handlers
    
    async def _handle_connect(self, sid, environ, client_auth):
        """Handle client connection"""
        print(f"Client connected -> sid: {sid}, environ: {environ}, client_auth: {client_auth}")
        
        data = {
            'timestamp': frappe_now(),
            'sid': sid,
            'site': get_site_name(frappe.local.site),
        }
        
        response = {
            'success': True,
            'message': 'Connected to frappe SocketIO server',
            'data': data,
        }
        
        await self.sio.emit('connected', response, to=sid)
    
    async def _handle_disconnect(self, sid, reason):
        """Handle client disconnection"""
        print(f"Client disconnected -> sid: {sid}, reason: {reason}")
    
    async def _handle_message(self, sid, data):
        """Handle generic message from client"""
        print(f"Message received from {sid}: {data}")
    
    async def _handle_ping(self, sid, data: Dict = {}):
        """Handle ping event from client"""        
        print(f"Ping received from {sid}: {data}")
        
        data_response = frappe._dict(data)
        data_response.message = 'pong'
        
        metadata = frappe._dict()
        metadata.timestamp = frappe_now()
        metadata.sid = sid
        metadata.site = get_site_name(frappe.local.site)

        response = Response.success(
            data=dict(data_response),
            metadata=dict(metadata),
        ).to_dict()

        await self.sio.emit('pong', response, to=sid)
        
        return response # Callback args

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
