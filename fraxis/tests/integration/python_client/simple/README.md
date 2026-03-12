# Fraxis Socket.IO Python Client - Simple Example

This directory contains a simple Python script demonstrating real-time consumption of async methods via Fraxis Socket.IO.

## Overview

The `async_method_execute.py` script shows how to:

1. **Connect** to the Fraxis Socket.IO server
2. **Execute** the `fraxis.api.process_values` async method
3. **Receive values in real-time** via `method:execute:progress` events as they're generated
4. **Display timing information** for each received value
5. **Get the final aggregated result** via ACK callback

This demonstrates the real-time streaming capability where the client receives and processes values incrementally as the server generates them, rather than waiting for all values to be accumulated.

## Requirements

- Python 3.10 or higher
- Access to a running Fraxis Socket.IO server
- Valid authentication token

## Installation

1. **Create a virtual environment** (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

## Configuration

Edit the `.env` file with your Fraxis server details:

```env
# Socket.IO server URL
SOCKETIO_SERVER=http://localhost:8005

# Authentication token (get from your Frappe site)
SOCKETIO_AUTH_TOKEN=your_actual_token_here

# Site name
SITE_NAME=yoursite.local

# Connection timeout in seconds
CONNECTION_TIMEOUT=10
```

### Getting Your Auth Token

To get a valid authentication token:

```bash
# From your Frappe bench directory
bench --site yoursite.local execute frappe.auth.get_api_key --args "['Administrator']"
```

Or use a session token from your browser's developer tools.

## Usage

Run the script:

```bash
python async_method_execute.py
```

### Expected Output

```
============================================================
Fraxis Socket.IO - Async Method Execution Example
============================================================
Server: http://localhost:8005
Site: aiservices.local
============================================================
Connecting to http://localhost:8005/api/method...
✓ Connected to /api/method

============================================================
Example 1: Processing Greek letters
============================================================

Executing process_values with 10 values...
Delay range: 50-100ms

Real-time progress (as values are generated):
------------------------------------------------------------
  [ 10.0%] Received value: alpha      (+ 87.342 ms)
  [ 20.0%] Received value: beta       (+ 63.128 ms)
  [ 30.0%] Received value: gamma      (+ 91.754 ms)
  [ 40.0%] Received value: delta      (+ 72.489 ms)
  [ 50.0%] Received value: epsilon    (+ 55.213 ms)
  [ 60.0%] Received value: zeta       (+ 98.106 ms)
  [ 70.0%] Received value: eta        (+ 81.352 ms)
  [ 80.0%] Received value: theta      (+ 67.891 ms)
  [ 90.0%] Received value: iota       (+ 74.623 ms)
  [100.0%] Received value: kappa      (+ 88.457 ms)
------------------------------------------------------------

✓ Final Result:
  Total values processed: 10
  Server elapsed time: 780.355 ms
  Client elapsed time: 832.147 ms
  Async: True
  Async Iterator: True

✓ Values received via progress events: 10
  All values received in real-time! ✓

============================================================
Example 2: Processing with longer delays
============================================================
...
```

## How It Works

### Real-time Value Reception

The script demonstrates the key feature of async iterators in Fraxis:

1. **Progress Events**: As `process_values` consumes the async iterator, each yielded value triggers a `method:execute:progress` event
2. **Immediate Reception**: The client receives these events in real-time via the `on_progress` handler
3. **Event-Driven**: No polling required - events are pushed from server to client as they occur
4. **Final Result**: After all values are processed, the ACK callback returns the complete aggregated result

### Event Flow

```
Client                                    Server
  |                                         |
  |--- method:execute ------------------>  |
  |    (process_values)                    |
  |                                         |
  |                    [delay ~50-100ms]   |
  |<-- method:execute:progress ----------  |  (value 1)
  |    { value: "alpha", delta_ms: 87 }   |
  |                                         |
  |                    [delay ~50-100ms]   |
  |<-- method:execute:progress ----------  |  (value 2)
  |    { value: "beta", delta_ms: 63 }    |
  |                                         |
  |                    ... (continues)      |
  |                                         |
  |<-- method:execute:success -----------  |  (final result)
  |<-- ACK callback --------------------  |
  |    { total_values: 10, results: [...] }|
```

### Code Structure

- **FraxisAsyncClient**: Async Socket.IO client wrapper
  - `connect()`: Establishes connection with auth
  - `execute_process_values()`: Executes the method and handles ACK
  - `_handle_progress()`: Processes real-time progress events
  
- **Event Handlers**:
  - `on_progress`: Receives and displays each value as it's generated
  - `connect/disconnect`: Connection lifecycle management

## What Makes This "Real-time"?

Unlike traditional request-response patterns where the client waits for the complete result:

**Traditional (blocking)**:
```
Client sends request → [wait for all processing] → Receive complete result
```

**Fraxis Async Iterator (streaming)**:
```
Client sends request → Receive value 1 → Receive value 2 → ... → Receive final summary
                       (50ms later)     (100ms later)
```

Each value is received and can be processed **as soon as it's generated on the server**, enabling true real-time streaming of data.

## Troubleshooting

### Connection Issues

If you get connection errors:

1. **Check server is running**:
   ```bash
   ps aux | grep socketio-server
   ```

2. **Start the server** if not running:
   ```bash
   bench --site yoursite.local socketio-server
   ```

3. **Verify URL and port** in `.env` match your server configuration

### Authentication Errors

If authentication fails:

1. Verify your auth token is valid and not expired
2. Check that the token has proper permissions
3. Ensure the site name matches your Frappe site

### Timeout Issues

If methods timeout:

1. Increase `CONNECTION_TIMEOUT` in `.env`
2. Reduce the number of values or delay range in the script
3. Check server logs for errors

## Extending the Example

### Custom Values

Modify the `sample_values` list in `main()`:

```python
sample_values = ["custom1", "custom2", "custom3"]
```

### Adjust Timing

Change delay ranges:

```python
result = await client.execute_process_values(
    values=sample_values,
    min_ms=200,  # Longer delays
    max_ms=500
)
```

### Add More Methods

The `FraxisAsyncClient` can be extended to call other async methods:

```python
async def execute_custom_method(self, method_name: str, args: dict):
    result = await self.sio.call(
        'method:execute',
        {'method': method_name, 'args': args},
        namespace=self.namespace
    )
    return result
```

## Related Examples

- **JavaScript Client**: `../../javascript_client/scenarios/async_iterator.test.js`
- **Async Iterator Tests**: Full test suite for async iterator functionality
- **Original Python Example**: `async_iterator_example.py` (standalone demo)

## License

This example is part of the Fraxis project and is subject to the Mozilla Public License, v. 2.0.
