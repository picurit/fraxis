#!/usr/bin/env python3
"""
Fraxis Socket.IO Python Client - Async Method Execution Example

This script demonstrates how to consume the fraxis.api.process_values method
and receive values in real-time as they're generated via progress events.

The script shows:
1. Connecting to the Fraxis Socket.IO server
2. Executing the async method process_values
3. Receiving progress events in real-time as each value is generated
4. Displaying timing information for each received value
5. Getting the final result via ACK callback

This mimics the original async_iterator_example.py but using Socket.IO events
instead of print statements.
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import socketio

# Load environment variables from .env file
load_dotenv()

# Configuration from environment
SOCKETIO_SERVER = os.getenv('SOCKETIO_SERVER', 'http://localhost:8005')
AUTH_TOKEN = os.getenv('SOCKETIO_AUTH_TOKEN', 'test_token')
SITE_NAME = os.getenv('SITE_NAME', 'aiservices.local')
CONNECTION_TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', '10'))


class FraxisAsyncClient:
    """
    Fraxis Socket.IO async client for real-time method execution.
    
    This client connects to the /api/method namespace and handles:
    - Authentication
    - Method execution with ACK callbacks
    - Real-time progress event reception
    """
    
    def __init__(self, server_url: str, auth_token: str):
        """
        Initialize the Fraxis async client.
        
        Args:
            server_url: Socket.IO server URL (e.g., http://localhost:8005)
            auth_token: Authentication token for the site
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.namespace = '/api/method'
        
        # Create async Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,
            engineio_logger=False
        )
        
        # Storage for received values
        self.received_values = []
        self.connection_ready = asyncio.Event()
        
        # Setup event handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers."""
        
        @self.sio.event(namespace=self.namespace)
        async def connect():
            """Called when connected to the namespace."""
            print(f"✓ Connected to {self.namespace}")
            self.connection_ready.set()
        
        @self.sio.event(namespace=self.namespace)
        async def disconnect():
            """Called when disconnected from the namespace."""
            print(f"✗ Disconnected from {self.namespace}")
            self.connection_ready.clear()
        
        @self.sio.event(namespace=self.namespace)
        async def connect_error(data):
            """Called on connection error."""
            print(f"✗ Connection error: {data}")
        
        # Register progress event handler
        @self.sio.on('method:execute:progress', namespace=self.namespace)
        async def on_progress(data):
            """
            Called when a progress event is received.
            
            For process_values, this is emitted for each value as it's generated.
            The data includes:
            - percent: progress percentage
            - title: "Processing Values"
            - description: human-readable description with timing
            - data: { value, delta_ms, timestamp }
            """
            await self._handle_progress(data)
    
    async def _handle_progress(self, data: dict):
        """
        Handle progress events and display real-time updates.
        
        Args:
            data: Progress event payload
        """
        # Extract progress information
        percent = data.get('percent', 0)
        title = data.get('title', 'Processing')
        description = data.get('description', '')
        partial_data = data.get('data', {})
        
        # Extract value and timing from the partial result
        value = partial_data.get('value', 'N/A')
        delta_ms = partial_data.get('delta_ms', 0)
        timestamp = partial_data.get('timestamp', '')
        
        # Store the received value
        self.received_values.append({
            'value': value,
            'delta_ms': delta_ms,
            'timestamp': timestamp,
            'percent': percent
        })
        
        # Display real-time update (mimics the original example's print output)
        print(f"  [{percent:5.1f}%] Received value: {value:10s} (+{delta_ms:7.3f} ms)")
    
    async def connect(self) -> bool:
        """
        Connect to the Fraxis Socket.IO server.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            print(f"Connecting to {self.server_url}{self.namespace}...")
            
            # Connect with authentication
            await self.sio.connect(
                self.server_url,
                namespaces=[self.namespace],
                auth={'token': self.auth_token},
                wait_timeout=CONNECTION_TIMEOUT
            )
            
            # Wait for connection to be ready
            await asyncio.wait_for(
                self.connection_ready.wait(),
                timeout=CONNECTION_TIMEOUT
            )
            
            return True
            
        except asyncio.TimeoutError:
            print(f"✗ Connection timeout after {CONNECTION_TIMEOUT} seconds")
            return False
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the Socket.IO server."""
        if self.sio.connected:
            await self.sio.disconnect()
            print("Disconnected from server")
    
    async def execute_process_values(
        self,
        values: list[str],
        min_ms: int = 100,
        max_ms: int = 300
    ) -> Optional[dict]:
        """
        Execute the fraxis.api.process_values method and receive values in real-time.
        
        This method:
        1. Emits the method:execute event with the method name and arguments
        2. Receives progress events as each value is generated (handled by on_progress)
        3. Returns the final result via ACK callback
        
        Args:
            values: List of string values to process
            min_ms: Minimum delay in milliseconds between values
            max_ms: Maximum delay in milliseconds between values
        
        Returns:
            dict: Final result with all values and timing information
        """
        # Clear previous results
        self.received_values = []
        
        print(f"\nExecuting process_values with {len(values)} values...")
        print(f"Delay range: {min_ms}-{max_ms}ms")
        print(f"\nReal-time progress (as values are generated):")
        print("-" * 60)
        
        try:
            # Emit method:execute event and wait for ACK response
            # The progress events will be received asynchronously via the on_progress handler
            result = await self.sio.call(
                'method:execute',
                {
                    'method': 'fraxis.api.process_values',
                    'args': {
                        'values': values,
                        'min_ms': min_ms,
                        'max_ms': max_ms
                    }
                },
                namespace=self.namespace,
                timeout=30  # Allow enough time for all values to be processed
            )
            
            print("-" * 60)
            
            # Check if the result is successful
            if result.get('error_stack') and len(result['error_stack']) > 0:
                print(f"\n✗ Method execution failed:")
                for error in result['error_stack']:
                    print(f"  - {error.get('message', 'Unknown error')}")
                return None
            
            # Extract the data from the response envelope
            data = result.get('data', {})
            
            return data
            
        except asyncio.TimeoutError:
            print("\n✗ Method execution timeout")
            return None
        except Exception as e:
            print(f"\n✗ Method execution error: {e}")
            return None


async def main():
    """
    Main function demonstrating real-time async method execution.
    
    This example shows how to:
    1. Connect to Fraxis Socket.IO server
    2. Execute process_values method
    3. Receive values in real-time via progress events
    4. Display timing information for each value
    5. Get the final aggregated result
    """
    print("=" * 60)
    print("Fraxis Socket.IO - Async Method Execution Example")
    print("=" * 60)
    print(f"Server: {SOCKETIO_SERVER}")
    print(f"Site: {SITE_NAME}")
    print("=" * 60)
    
    # Create client instance
    client = FraxisAsyncClient(SOCKETIO_SERVER, AUTH_TOKEN)
    
    try:
        # Connect to the server
        if not await client.connect():
            print("\nFailed to connect to server. Exiting.")
            return 1
        
        # Example 1: Process a list of Greek letters
        print("\n" + "=" * 60)
        print("Example 1: Processing Greek letters")
        print("=" * 60)
        
        sample_values = [
            "alpha", "beta", "gamma", "delta", "epsilon",
            "zeta", "eta", "theta", "iota", "kappa"
        ]
        
        start_time = datetime.now()
        result = await client.execute_process_values(
            values=sample_values,
            min_ms=50,
            max_ms=100
        )
        end_time = datetime.now()
        
        if result:
            print("\n✓ Final Result:")
            print(f"  Total values processed: {result.get('total_values', 0)}")
            print(f"  Server elapsed time: {result.get('total_elapsed_ms', 0):.3f} ms")
            print(f"  Client elapsed time: {(end_time - start_time).total_seconds() * 1000:.3f} ms")
            print(f"  Async: {result.get('async', False)}")
            print(f"  Async Iterator: {result.get('async_iterator', False)}")
            
            # Verify all values were received via progress events
            print(f"\n✓ Values received via progress events: {len(client.received_values)}")
            if len(client.received_values) == len(sample_values):
                print("  All values received in real-time! ✓")
            else:
                print(f"  Warning: Expected {len(sample_values)}, got {len(client.received_values)}")
        
        # Example 2: Process a shorter list with longer delays
        print("\n" + "=" * 60)
        print("Example 2: Processing with longer delays")
        print("=" * 60)
        
        sample_values_2 = ["uno", "dos", "tres", "cuatro", "cinco"]
        
        start_time = datetime.now()
        result2 = await client.execute_process_values(
            values=sample_values_2,
            min_ms=100,
            max_ms=200
        )
        end_time = datetime.now()
        
        if result2:
            print("\n✓ Final Result:")
            print(f"  Total values processed: {result2.get('total_values', 0)}")
            print(f"  Server elapsed time: {result2.get('total_elapsed_ms', 0):.3f} ms")
            print(f"  Client elapsed time: {(end_time - start_time).total_seconds() * 1000:.3f} ms")
            print(f"\n✓ Values received via progress events: {len(client.received_values)}")
        
        print("\n" + "=" * 60)
        print("Examples completed successfully!")
        print("=" * 60)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Always disconnect
        await client.disconnect()


if __name__ == '__main__':
    """Entry point for the script."""
    # Check Python version
    if sys.version_info < (3, 10):
        print("Error: This script requires Python 3.10 or higher")
        sys.exit(1)
    
    # Run the async main function
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
