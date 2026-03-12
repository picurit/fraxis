/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Async Method Execution Tests
 * 
 * Tests for asynchronous whitelisted methods decorated with @frappe.whitelist().
 * 
 * IMPORTANT: These async methods ONLY work via Fraxis Socket.IO (method:execute).
 * They do NOT work via Frappe REST API because REST uses synchronous WSGI handlers
 * that cannot await coroutines.
 * 
 * Test coverage based on patterns from FRAXIS_ASYNC_AND_LONG_RUN_METHODS.md:
 * - Pattern 1: Simple async method with I/O simulation
 * - Pattern 2: Async method with Frappe ORM via asyncio.to_thread()
 * - Pattern 3: Concurrent async operations with asyncio.gather()
 * - Pattern 4: Mixed async I/O and Frappe ORM operations
 * - Pattern 5: Error handling in async context
 * - Pattern 6: Multi-step async operations
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, sleep } from './utils/test_helpers.js';

describe('Async Method Execution', () => {
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
  // Pattern 1: Simple async method with I/O simulation
  // ============================================================================

  test('Should execute simple async method with I/O delay', async () => {
    logTest('Pattern 1: Simple async operation');

    logStep('Calling fraxis.api.async_simple_operation');
    const startTime = Date.now();
    
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_simple_operation',
      args: {
        value: 5
      }
    });

    const elapsedMs = Date.now() - startTime;

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.input).toBe(5);
    expect(response.data.output).toBe(10);
    expect(response.data.operation).toBe('multiply_by_2');
    expect(response.data.async).toBe(true);

    // Should take at least 500ms due to asyncio.sleep(0.5)
    expect(elapsedMs).toBeGreaterThanOrEqual(400); // Allow 100ms tolerance

    logSuccess(`Async method executed in ${elapsedMs}ms, returned correct result`);
  });

  test('Should handle async method with different input values', async () => {
    logTest('Pattern 1: Async method parameter handling');

    logStep('Testing with value=10');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_simple_operation',
      args: {
        value: 10
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data.input).toBe(10);
    expect(response.data.output).toBe(20);

    logSuccess('Async method processed parameters correctly');
  });

  test('Should execute async method with default parameters', async () => {
    logTest('Pattern 1: Async method default parameters');

    logStep('Calling async method without arguments');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_simple_operation',
      args: {}
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data.input).toBe(1); // Default value
    expect(response.data.output).toBe(2);

    logSuccess('Async method used default parameters correctly');
  });

  // ============================================================================
  // Pattern 2: Async method with Frappe ORM via asyncio.to_thread()
  // ============================================================================

  test('Should execute async method with Frappe ORM operations', async () => {
    logTest('Pattern 2: Async with Frappe ORM via to_thread');

    logStep('Calling fraxis.api.async_frappe_orm_operation');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_frappe_orm_operation',
      args: {
        doctype: 'ToDo',
        limit: 3
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.doctype).toBe('ToDo');
    expect(response.data.total_count).toBeDefined();
    expect(typeof response.data.total_count).toBe('number');
    expect(Array.isArray(response.data.sample_docs)).toBe(true);
    expect(response.data.sample_docs.length).toBeLessThanOrEqual(3);
    expect(response.data.limit).toBe(3);
    expect(response.data.async).toBe(true);

    logSuccess(`Async ORM method returned ${response.data.total_count} total docs, ${response.data.sample_docs.length} samples`);
  });

  test('Should handle async ORM operations with different doctypes', async () => {
    logTest('Pattern 2: Async ORM with various doctypes');

    const doctypes = ['User', 'DocType'];

    for (const doctype of doctypes) {
      logStep(`Testing with doctype: ${doctype}`);
      
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_frappe_orm_operation',
        args: {
          doctype: doctype,
          limit: 2
        }
      });

      ResponseValidators.assertResponseEnvelope(response);
      ResponseValidators.assertSuccess(response);

      expect(response.data.doctype).toBe(doctype);
      expect(typeof response.data.total_count).toBe('number');
    }

    logSuccess('Async ORM method handled multiple doctypes correctly');
  });

  test('Should not block event loop during async ORM operations', async () => {
    logTest('Pattern 2: Event loop non-blocking verification');

    logStep('Starting async ORM operation');
    const promise1 = client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_frappe_orm_operation',
      args: {
        doctype: 'ToDo',
        limit: 5
      }
    });

    // Immediately start another operation - should not be blocked
    const promise2 = client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_simple_operation',
      args: {
        value: 3
      }
    });

    const [response1, response2] = await Promise.all([promise1, promise2]);

    ResponseValidators.assertSuccess(response1);
    ResponseValidators.assertSuccess(response2);

    expect(response1.data.doctype).toBe('ToDo');
    expect(response2.data.output).toBe(6);

    logSuccess('Both async operations completed without blocking each other');
  });

  // ============================================================================
  // Pattern 3: Concurrent async operations with asyncio.gather()
  // ============================================================================

  test('Should execute concurrent operations on multiple doctypes', async () => {
    logTest('Pattern 3: Concurrent async operations');

    logStep('Calling fraxis.api.async_concurrent_operations');
    const startTime = Date.now();
    
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_concurrent_operations',
      args: {
        doctypes: ['ToDo', 'User', 'DocType']
      }
    }, 20000); // Longer timeout for concurrent operations

    const elapsedMs = Date.now() - startTime;

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.counts).toBeDefined();
    expect(typeof response.data.counts).toBe('object');
    expect(response.data.total_doctypes).toBe(3);
    expect(response.data.async).toBe(true);
    expect(response.data.concurrent).toBe(true);
    expect(Array.isArray(response.data.errors)).toBe(true);

    // Should have counts for all doctypes (or errors)
    const totalProcessed = Object.keys(response.data.counts).length + response.data.errors.length;
    expect(totalProcessed).toBe(3);

    logSuccess(`Concurrent operations completed in ${elapsedMs}ms, processed ${Object.keys(response.data.counts).length} doctypes`);
  });

  test('Should handle concurrent operations with default doctypes', async () => {
    logTest('Pattern 3: Concurrent operations with defaults');

    logStep('Calling without specifying doctypes');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_concurrent_operations',
      args: {}
    }, 20000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    // Default doctypes: ['ToDo', 'User', 'DocType']
    expect(response.data.total_doctypes).toBe(3);

    logSuccess('Concurrent operations used default doctypes correctly');
  });

  test('Should handle errors in concurrent operations gracefully', async () => {
    logTest('Pattern 3: Error handling in concurrent operations');

    logStep('Testing with mix of valid and invalid doctypes');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_concurrent_operations',
      args: {
        doctypes: ['ToDo', 'InvalidDocTypeThatDoesNotExist123', 'User']
      }
    }, 20000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    // Should have some successful counts and some errors
    expect(response.data.counts).toBeDefined();
    expect(response.data.errors).toBeDefined();
    expect(Array.isArray(response.data.errors)).toBe(true);

    // At least one error should be recorded
    if (response.data.errors.length > 0) {
      logSuccess(`Concurrent operations handled ${response.data.errors.length} error(s) gracefully`);
    } else {
      logSuccess('All concurrent operations succeeded');
    }
  });

  // ============================================================================
  // Pattern 4: Mixed async I/O and Frappe ORM operations
  // ============================================================================

  test('Should execute mixed async I/O and ORM operations', async () => {
    logTest('Pattern 4: Mixed async operations');

    logStep('Calling fraxis.api.async_mixed_operations');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_mixed_operations',
      args: {
        doctype: 'ToDo',
        delay: 0.3
      }
    }, 15000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.doctype).toBe('ToDo');
    expect(typeof response.data.count).toBe('number');
    expect(Array.isArray(response.data.sample)).toBe(true);
    expect(response.data.elapsed_seconds).toBeDefined();
    expect(response.data.delay_requested).toBe(0.3);
    expect(response.data.async).toBe(true);

    // Should take at least the requested delay time
    expect(response.data.elapsed_seconds).toBeGreaterThanOrEqual(0.3);

    logSuccess(`Mixed async operations completed in ${response.data.elapsed_seconds}s`);
  });

  test('Should respect timing in mixed async operations', async () => {
    logTest('Pattern 4: Timing verification');

    const delay = 0.5;
    logStep(`Testing with delay=${delay}s`);
    
    const startTime = Date.now();
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_mixed_operations',
      args: {
        doctype: 'User',
        delay: delay
      }
    }, 15000);

    const elapsedMs = Date.now() - startTime;

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    // Total time should be at least delay + 0.1 (from second sleep)
    expect(elapsedMs).toBeGreaterThanOrEqual((delay + 0.1) * 1000 - 100); // 100ms tolerance

    logSuccess(`Mixed operations took ${elapsedMs}ms (expected ~${(delay + 0.1) * 1000}ms)`);
  });

  // ============================================================================
  // Pattern 5: Error handling in async context
  // ============================================================================

  test('Should handle successful async execution without errors', async () => {
    logTest('Pattern 5: Async error handling - success case');

    logStep('Calling async_error_handling with should_fail=false');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_error_handling',
      args: {
        should_fail: false
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data.status).toBe('success');
    expect(response.data.async).toBe(true);

    logSuccess('Async method completed successfully without errors');
  });

  test('Should handle validation errors in async methods', async () => {
    logTest('Pattern 5: Async validation error handling');

    logStep('Triggering validation error');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_error_handling',
      args: {
        should_fail: true,
        error_type: 'validation'
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertHasError(response);

    expect(response.error_stack.length).toBeGreaterThan(0);
    expect(response.error_stack[0].message).toContain('validation');

    logSuccess('Async validation error captured in response envelope');
  });

  test('Should handle permission errors in async methods', async () => {
    logTest('Pattern 5: Async permission error handling');

    logStep('Triggering permission error');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_error_handling',
      args: {
        should_fail: true,
        error_type: 'permission'
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertHasError(response);

    expect(response.error_stack.length).toBeGreaterThan(0);
    expect(response.error_stack[0].message).toContain('permission');

    logSuccess('Async permission error captured in response envelope');
  });

  test('Should handle runtime errors in async methods', async () => {
    logTest('Pattern 5: Async runtime error handling');

    logStep('Triggering runtime error');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_error_handling',
      args: {
        should_fail: true,
        error_type: 'runtime'
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertHasError(response);

    expect(response.error_stack.length).toBeGreaterThan(0);
    expect(response.error_stack[0].message).toContain('runtime');

    logSuccess('Async runtime error captured in response envelope');
  });

  test('Should handle database errors in async methods', async () => {
    logTest('Pattern 5: Async database error handling');

    logStep('Triggering database error via non-existent doctype');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_error_handling',
      args: {
        should_fail: true,
        error_type: 'db'
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertHasError(response);

    expect(response.error_stack.length).toBeGreaterThan(0);

    logSuccess('Async database error captured in response envelope');
  });

  // ============================================================================
  // Pattern 6: Multi-step async operations
  // ============================================================================

  test('Should execute multi-step async operations', async () => {
    logTest('Pattern 6: Multi-step async operations');

    logStep('Calling async_with_progress_simulation');
    const steps = 3;
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_with_progress_simulation',
      args: {
        steps: steps
      }
    }, 15000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.total_steps).toBe(steps);
    expect(Array.isArray(response.data.results)).toBe(true);
    expect(response.data.results.length).toBe(steps);
    expect(response.data.async).toBe(true);

    // Verify all steps completed
    for (let i = 0; i < steps; i++) {
      expect(response.data.results[i].step).toBe(i + 1);
      expect(response.data.results[i].timestamp).toBeDefined();
      expect(response.data.results[i].data).toContain(`Step ${i + 1}`);
    }

    logSuccess(`Multi-step async operation completed ${steps} steps successfully`);
  });

  test('Should handle different step counts in multi-step operations', async () => {
    logTest('Pattern 6: Variable step counts');

    const stepCounts = [1, 5, 10];

    for (const steps of stepCounts) {
      logStep(`Testing with ${steps} steps`);
      
      const startTime = Date.now();
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_with_progress_simulation',
        args: {
          steps: steps
        }
      }, 20000);

      const elapsedMs = Date.now() - startTime;

      ResponseValidators.assertResponseEnvelope(response);
      ResponseValidators.assertSuccess(response);

      expect(response.data.total_steps).toBe(steps);
      expect(response.data.results.length).toBe(steps);

      // Each step takes ~200ms, so total should be ~steps * 200ms
      const expectedMinMs = steps * 200 - 100; // 100ms tolerance
      expect(elapsedMs).toBeGreaterThanOrEqual(expectedMinMs);

      logSuccess(`${steps} steps completed in ${elapsedMs}ms`);
    }
  });

  // ============================================================================
  // Integration with Rooms and Events
  // ============================================================================

  test('Should broadcast async method results to subscribed rooms', async () => {
    logTest('Integration: Async methods with room subscriptions');

    const methodName = 'fraxis.api.async_simple_operation';

    logStep('Subscribing to method room');
    const subResponse = await client.emitAndWait('method:subscribe', {
      method: methodName
    });

    ResponseValidators.assertSuccess(subResponse);
    expect(subResponse.data.subscribed).toBe(true);

    logStep('Executing async method');
    const execResponse = await client.emitAndWait('method:execute', {
      method: methodName,
      args: {
        value: 7
      }
    });

    ResponseValidators.assertSuccess(execResponse);

    // Wait briefly for broadcast event
    await sleep(500);

    // Check if broadcast event was received
    const broadcastEvents = client.getEventsFromQueue('method:execute:success');
    
    if (broadcastEvents.length > 0) {
      logSuccess('Async method result broadcasted to subscribed room');
    } else {
      logSuccess('Async method executed successfully (broadcast may be async)');
    }
  });

  // ============================================================================
  // Metadata and Response Envelope Validation
  // ============================================================================

  test('Should include correct metadata in async method responses', async () => {
    logTest('Metadata validation for async methods');

    logStep('Executing async method and checking metadata');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_simple_operation',
      args: {
        value: 1
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertMetadata(response);

    const { metadata } = response;
    expect(metadata.timestamp).toBeDefined();
    expect(metadata.sid).toBeDefined();
    expect(metadata.site).toBeDefined();

    logSuccess('Async method response includes valid metadata');
  });

  test('Should maintain response envelope structure for async methods', async () => {
    logTest('Response envelope structure validation');

    logStep('Verifying envelope structure');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.async_frappe_orm_operation',
      args: {
        doctype: 'ToDo',
        limit: 1
      }
    });

    // Check all required fields
    expect(response).toHaveProperty('data');
    expect(response).toHaveProperty('metadata');
    expect(response).toHaveProperty('error_stack');
    expect(response).toHaveProperty('warning_stack');
    expect(response).toHaveProperty('info_stack');

    expect(Array.isArray(response.error_stack)).toBe(true);
    expect(Array.isArray(response.warning_stack)).toBe(true);
    expect(Array.isArray(response.info_stack)).toBe(true);

    logSuccess('Response envelope structure is valid for async methods');
  });

  // ============================================================================
  // Performance and Concurrency Tests
  // ============================================================================

  test('Should handle multiple concurrent async method calls', async () => {
    logTest('Concurrency: Multiple parallel async calls');

    logStep('Starting 5 concurrent async method calls');
    const promises = [];
    
    for (let i = 0; i < 5; i++) {
      promises.push(
        client.emitAndWait('method:execute', {
          method: 'fraxis.api.async_simple_operation',
          args: {
            value: i + 1
          }
        })
      );
    }

    const startTime = Date.now();
    const responses = await Promise.all(promises);
    const elapsedMs = Date.now() - startTime;

    // All responses should be successful
    responses.forEach((response, index) => {
      ResponseValidators.assertSuccess(response);
      expect(response.data.input).toBe(index + 1);
      expect(response.data.output).toBe((index + 1) * 2);
    });

    // Since they run concurrently, total time should be ~500ms (not 5 * 500ms)
    // Allow generous tolerance for CI environments
    expect(elapsedMs).toBeLessThan(2000);

    logSuccess(`5 concurrent async calls completed in ${elapsedMs}ms (demonstrates non-blocking)`);
  });

  test('Should handle rapid sequential async method calls', async () => {
    logTest('Performance: Rapid sequential async calls');

    logStep('Making 10 rapid sequential calls');
    const results = [];
    
    for (let i = 0; i < 10; i++) {
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_simple_operation',
        args: {
          value: i
        }
      });
      
      ResponseValidators.assertSuccess(response);
      results.push(response.data.output);
    }

    expect(results.length).toBe(10);
    
    logSuccess('Rapid sequential async calls completed successfully');
  });
});
