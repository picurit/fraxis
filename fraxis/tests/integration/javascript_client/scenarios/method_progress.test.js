/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Method Progress Tests - Option F Hybrid Approach
 * 
 * Tests for progress notification functionality in Fraxis Socket.IO.
 * Covers both execution contexts:
 * 
 * 1. In-Process Progress (method:execute with async methods):
 *    - Progress callback injection via closure capture
 *    - Direct Socket.IO emit to requesting client's private room
 *    - Arbitrary payload support via `data` field
 * 
 * 2. Out-of-Process Progress (method:enqueue with RQ workers):
 *    - Redis pub/sub relay from RQ worker to Fraxis listener
 *    - Event translation: fraxis_method_progress → method:enqueue:progress
 *    - Room translation: task_progress:{task_id} → method:{method}:{task_id}
 *    - Arbitrary payload support via `data` field
 * 
 * Based on IMPLEMENTATION.md Progress Notification Architecture section.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, sleep } from './utils/test_helpers.js';

describe('Method Progress - Hybrid Approach', () => {
  let client;

  beforeEach(async () => {
    client = new FraxisSocketIOClient(null, '/api/method');
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
  });

  afterEach(async () => {
    if (client && client.isConnected) {
      await client.disconnect();
    }
  });

  // ============================================================================
  // IN-PROCESS PROGRESS: method:execute with async methods
  // ============================================================================

  describe('method:execute - In-Process Async Progress', () => {
    
    test('Should receive progress events from async method with injected callback', async () => {
      logTest('Async method with progress injection');

      const progressEvents = [];
      
      // Listen for progress events
      client.on('method:execute:progress', (data) => {
        logStep(`Progress: ${data.percent}% - ${data.description}`);
        progressEvents.push(data);
      });

      logStep('Calling fraxis.api.async_with_progress_simulation with 3 steps');
      
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_with_progress_simulation',
        args: {
          steps: 3
        }
      });

      // Validate final result
      ResponseValidators.assertResponseEnvelope(response);
      ResponseValidators.assertSuccess(response);
      expect(response.data.total_steps).toBe(3);
      expect(response.data.results).toHaveLength(3);

      // Validate progress events
      expect(progressEvents.length).toBe(3); // One progress event per step
      
      // Check first progress event
      expect(progressEvents[0].percent).toBeCloseTo(33.3, 1);
      expect(progressEvents[0].title).toBe('Processing Steps');
      expect(progressEvents[0].description).toBe('Step 1 of 3');
      expect(progressEvents[0].data).toBeDefined();
      expect(progressEvents[0].data.step).toBe(1);

      // Check last progress event
      expect(progressEvents[2].percent).toBe(100);
      expect(progressEvents[2].description).toBe('Step 3 of 3');
      expect(progressEvents[2].data.step).toBe(3);

      logSuccess(`Received ${progressEvents.length} progress events with arbitrary payloads`);
    });

    test('Should handle concurrent method:execute calls with isolated progress', async () => {
      logTest('Concurrent async methods with independent progress streams');

      const progressClient1 = [];
      const progressClient2 = [];
      
      // Client 1 listens for its progress
      client.on('method:execute:progress', (data) => {
        progressClient1.push(data);
      });

      // Create second client
      const client2 = new FraxisSocketIOClient(null, '/api/method');
      await client2.connectWithAuth({ token: TestFixtures.getAuthToken() });
      
      client2.on('method:execute:progress', (data) => {
        progressClient2.push(data);
      });

      logStep('Starting concurrent method:execute calls with different step counts');

      // Execute concurrently - client1 with 2 steps, client2 with 4 steps
      const [response1, response2] = await Promise.all([
        client.emitAndWait('method:execute', {
          method: 'fraxis.api.async_with_progress_simulation',
          args: { steps: 2 }
        }),
        client2.emitAndWait('method:execute', {
          method: 'fraxis.api.async_with_progress_simulation',
          args: { steps: 4 }
        })
      ]);

      // Validate both completed successfully
      ResponseValidators.assertSuccess(response1);
      ResponseValidators.assertSuccess(response2);

      // Validate progress isolation via closure capture
      expect(progressClient1.length).toBe(2); // Client 1 only received its 2 events
      expect(progressClient2.length).toBe(4); // Client 2 only received its 4 events

      // Verify each client received correct progress sequences
      expect(progressClient1[0].percent).toBeCloseTo(50, 0);
      expect(progressClient1[1].percent).toBe(100);
      
      expect(progressClient2[0].percent).toBe(25);
      expect(progressClient2[3].percent).toBe(100);

      await client2.disconnect();
      
      logSuccess('Concurrent executions had isolated progress streams');
    });

    test('Should support arbitrary data payloads in progress events', async () => {
      logTest('Progress events with structured data payloads');

      const progressEvents = [];
      
      client.on('method:execute:progress', (data) => {
        progressEvents.push(data);
      });

      await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_with_progress_simulation',
        args: { steps: 2 }
      });

      // Validate data field contains structured payload
      expect(progressEvents[0].data).toBeDefined();
      expect(progressEvents[0].data.step).toBe(1);
      expect(progressEvents[0].data.timestamp).toBeDefined();
      expect(progressEvents[0].data.data).toContain('Step 1 completed');

      // Second event should have different data
      expect(progressEvents[1].data.step).toBe(2);

      logSuccess('Progress events carried arbitrary structured payloads');
    });

    test('Should work with method that does not use progress callback', async () => {
      logTest('Method without progress parameter should not emit progress');

      const progressEvents = [];
      
      client.on('method:execute:progress', (data) => {
        progressEvents.push(data);
      });

      logStep('Calling async method without progress parameter');
      
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_simple_operation',
        args: { value: 5 }
      });

      ResponseValidators.assertSuccess(response);
      expect(response.data.output).toBe(10);

      // Should not receive any progress events
      expect(progressEvents.length).toBe(0);

      logSuccess('Method without progress callback did not emit progress events');
    });
  });

  // ============================================================================
  // OUT-OF-PROCESS PROGRESS: method:enqueue with RQ workers
  // ============================================================================

  describe('method:enqueue - Out-of-Process RQ Progress', () => {
    
    test('Should receive progress events from enqueued method via Redis relay', async () => {
      logTest('RQ job with progress via Redis pub/sub');

      const progressEvents = [];
      
      // Listen for progress events
      client.on('method:enqueue:progress', (data) => {
        logStep(`Progress: ${data.percent}% - ${data.description}`);
        progressEvents.push(data);
      });

      logStep('Enqueueing fraxis.api.long_running_sync_job with 3 iterations');
      
      const response = await client.emitAndWait('method:enqueue', {
        method: 'fraxis.api.long_running_sync_job',
        args: {
          iterations: 3
        }
      });

      // Validate enqueue response
      ResponseValidators.assertResponseEnvelope(response);
      ResponseValidators.assertSuccess(response);
      expect(response.data.task_id).toBeDefined();

      const taskId = response.data.task_id;
      logStep(`Job enqueued with task_id: ${taskId}`);

      // Wait for job completion with timeout
      const jobResult = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Job did not complete within 10 seconds'));
        }, 10000);

        client.once('method:enqueue:success', (data) => {
          clearTimeout(timeout);
          resolve(data);
        });

        client.once('method:enqueue:failure', (data) => {
          clearTimeout(timeout);
          reject(new Error(`Job failed: ${data.error}`));
        });
      });

      // Validate job completion
      expect(jobResult.task_id).toBe(taskId);
      expect(jobResult.result).toBeDefined();
      expect(jobResult.result.total_iterations).toBe(3);

      // Validate progress events were received
      // Note: Client receives events from both job-specific room and method-level room,
      // so we get 2 events per iteration (6 total for 3 iterations)
      expect(progressEvents.length).toBeGreaterThanOrEqual(3);
      
      // Filter unique events by iteration number to validate content
      const uniqueEvents = [];
      const seenIterations = new Set();
      for (const event of progressEvents) {
        if (event.data && !seenIterations.has(event.data.iteration)) {
          uniqueEvents.push(event);
          seenIterations.add(event.data.iteration);
        }
      }
      
      expect(uniqueEvents.length).toBe(3); // One unique event per iteration
      
      // Check first unique progress event
      expect(uniqueEvents[0].task_id).toBe(taskId);
      expect(uniqueEvents[0].percent).toBeCloseTo(33.3, 1);
      expect(uniqueEvents[0].title).toBe('Processing Long Job');
      expect(uniqueEvents[0].description).toContain('iteration 1 of 3');
      
      // Check data payload (arbitrary structured data)
      expect(uniqueEvents[0].data).toBeDefined();
      expect(uniqueEvents[0].data.iteration).toBe(1);
      expect(uniqueEvents[0].data.timestamp).toBeDefined();

      logSuccess(`Received ${progressEvents.length} progress events (${uniqueEvents.length} unique) via Redis relay`);
    });

    test('Should translate Frappe rooms to Fraxis rooms', async () => {
      logTest('Redis listener translates task_progress:{id} to method:{name}:{id}');

      // The test implicitly validates room translation by successfully receiving events
      // If translation failed, the client would not receive events because it's subscribed
      // to method:{method_name}:{task_id}, not task_progress:{task_id}

      const progressEvents = [];
      
      client.on('method:enqueue:progress', (data) => {
        progressEvents.push(data);
      });

      const response = await client.emitAndWait('method:enqueue', {
        method: 'fraxis.api.long_running_sync_job',
        args: { iterations: 2 }
      });

      ResponseValidators.assertSuccess(response);

      // Wait for at least one progress event
      await new Promise((resolve) => {
        client.once('method:enqueue:progress', () => {
          resolve();
        });
      });

      expect(progressEvents.length).toBeGreaterThan(0);
      expect(progressEvents[0].task_id).toBeDefined();

      logSuccess('Room translation from Frappe to Fraxis format succeeded');
    });

    test('Should support arbitrary data payloads in RQ progress', async () => {
      logTest('RQ progress with structured data payloads');

      const progressEvents = [];
      
      client.on('method:enqueue:progress', (data) => {
        progressEvents.push(data);
      });

      await client.emitAndWait('method:enqueue', {
        method: 'fraxis.api.long_running_sync_job',
        args: { iterations: 2 }
      });

      // Wait for at least one progress event
      await new Promise((resolve) => {
        client.once('method:enqueue:progress', () => {
          resolve();
        });
      });

      // Validate data field contains structured payload from RQ worker
      expect(progressEvents[0].data).toBeDefined();
      expect(progressEvents[0].data.iteration).toBeDefined();
      expect(progressEvents[0].data.timestamp).toBeDefined();

      logSuccess('RQ progress events carried arbitrary payloads');
    });
  });

  // ============================================================================
  // EDGE CASES
  // ============================================================================

  describe('Edge Cases', () => {
    
    test('Should handle rapid progress updates without data loss', async () => {
      logTest('Rapid progress updates stress test');

      const progressEvents = [];
      
      client.on('method:execute:progress', (data) => {
        progressEvents.push(data);
      });

      await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_with_progress_simulation',
        args: { steps: 10 } // More frequent updates
      });

      // Should receive all 10 progress events
      expect(progressEvents.length).toBe(10);
      
      // Verify sequence is correct
      for (let i = 0; i < 10; i++) {
        expect(progressEvents[i].data.step).toBe(i + 1);
      }

      logSuccess('All rapid progress updates received in correct order');
    });

    test('Should not break when progress callback is not used by method', async () => {
      logTest('Method signature without progress parameter');

      // Method should execute successfully even though handler injected progress
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_simple_operation',
        args: { value: 10 }
      });

      ResponseValidators.assertSuccess(response);
      expect(response.data.output).toBe(20);

      logSuccess('Method without progress parameter executed successfully');
    });
  });
});
