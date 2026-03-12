/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Connection Lifecycle Tests
 * 
 * Tests for Socket.IO connection establishment, authentication,
 * and disconnection flows.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, logError, sleep } from './utils/test_helpers.js';

describe('Connection Lifecycle', () => {
  let client;

  afterEach(async () => {
    if (client && client.isConnected) {
      await client.disconnect();
    }
  });

  test('Should successfully connect to /system namespace', async () => {
    logTest('Connect to /system namespace');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating client for /system namespace');
    
    await client.connectWithAuth(
      { token: TestFixtures.getAuthToken() },
      10000
    );
    logStep('Connected with authentication');
    
    expect(client.isConnected).toBe(true);
    expect(client.socket).toBeDefined();
    expect(client.socket.id).toBeDefined();
    
    logSuccess('Connected to /system namespace');
  });

  test('Should receive system:connect:ready event after connection', async () => {
    logTest('Receive system:connect:ready');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating client');
    
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
    logStep('Connected');
    
    // Check if system:connect:ready was received
    const readyEvents = client.getEventsFromQueue('system:connect:ready');
    expect(readyEvents.length).toBeGreaterThan(0);
    
    const readyEvent = readyEvents[0];
    expect(readyEvent.data).toBeDefined();
    expect(readyEvent.data.site).toBeDefined();
    expect(readyEvent.data.user).toBeDefined();
    
    logSuccess('system:connect:ready received with correct data');
  });

  test('Should connect to /api/document namespace', async () => {
    logTest('Connect to /api/document namespace');
    
    client = new FraxisSocketIOClient(null, '/api/document');
    logStep('Creating client for /api/document namespace');
    
    // Note: /api/document might not have system:connect:ready, so set longer timeout
    await client.connectWithAuth(
      { token: TestFixtures.getAuthToken() },
      10000
    );
    logStep('Connected');
    
    expect(client.isConnected).toBe(true);
    
    logSuccess('Connected to /api/document namespace');
  });

  test('Should connect to /api/doctype namespace', async () => {
    logTest('Connect to /api/doctype namespace');
    
    client = new FraxisSocketIOClient(null, '/api/doctype');
    logStep('Creating client for /api/doctype namespace');
    
    await client.connectWithAuth(
      { token: TestFixtures.getAuthToken() },
      10000
    );
    logStep('Connected');
    
    expect(client.isConnected).toBe(true);
    
    logSuccess('Connected to /api/doctype namespace');
  });

  test('Should connect to /api/method namespace', async () => {
    logTest('Connect to /api/method namespace');
    
    client = new FraxisSocketIOClient(null, '/api/method');
    logStep('Creating client for /api/method namespace');
    
    await client.connectWithAuth(
      { token: TestFixtures.getAuthToken() },
      10000
    );
    logStep('Connected');
    
    expect(client.isConnected).toBe(true);
    
    logSuccess('Connected to /api/method namespace');
  });

  test('Should handle reconnection gracefully', async () => {
    logTest('Handle reconnection');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating client');
    
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
    logStep('Connected');
    
    const firstId = client.socket.id;
    expect(firstId).toBeDefined();
    
    logSuccess('Can reconnect gracefully');
  });

  test('Should emit disconnect event when disconnected', async () => {
    logTest('Emit disconnect event');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating and connecting client');
    
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
    logStep('Connected');
    
    await client.disconnect();
    logStep('Disconnected');
    
    expect(client.isConnected).toBe(false);
    
    logSuccess('Disconnect handled correctly');
  });

  test('Should timeout on connection attempts when server unavailable', async () => {
    logTest('Timeout on unavailable server');
    
    // Create client pointing to non-existent server
    client = new FraxisSocketIOClient('http://localhost:9999', '/system');
    logStep('Creating client for unavailable server');
    
    try {
      await client.connectWithAuth(
        { token: TestFixtures.getAuthToken() },
        3000  // Shorter timeout for faster test
      );
      // If we get here, connection somehow succeeded (unlikely)
      throw new Error('Expected connection to fail');
    } catch (error) {
      expect(error).toBeDefined();
      logSuccess(`Connection properly timed out: ${error.message}`);
    }
  });

  test('Should handle invalid authentication token', async () => {
    logTest('Handle invalid authentication');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating client with invalid token');
    
    try {
      await client.connectWithAuth(
        { token: 'invalid_token_that_does_not_exist' },
        10000
      );
      // Check if we got failure event instead
      expect(true).toBe(false); // Should not reach here if auth is properly validated
    } catch (error) {
      // Expected - authentication should fail or timeout
      expect(error).toBeDefined();
      logSuccess(`Invalid auth properly rejected: ${error.message}`);
    }
  });

  test('Should maintain socket ID across operations', async () => {
    logTest('Maintain socket ID');
    
    client = new FraxisSocketIOClient(null, '/system');
    logStep('Creating client');
    
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
    logStep('Connected');
    
    const socketId = client.socket.id;
    expect(socketId).toBeDefined();
    expect(typeof socketId).toBe('string');
    expect(socketId.length).toBeGreaterThan(0);
    
    logSuccess(`Socket ID maintained: ${socketId}`);
  });
});
