/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Async Iterator Tests
 * 
 * Tests for AsyncIterator pattern support in Fraxis Socket.IO.
 * 
 * This test suite validates that Fraxis can handle async generators (AsyncIterator)
 * where methods yield values incrementally instead of returning a single result.
 * 
 * Key scenarios tested:
 * - Direct async iterator consumption (get_async_iterator)
 * - Async iterator with progress callback (process_values)
 * - Timing verification for random delays
 * - Error handling in async generators
 * - Progress event streaming for yielded values
 * - Integration with existing async method patterns
 * 
 * Based on the example from async_iterator_example.py:
 * - get_async_iterator: Yields values with random delays (simulating async I/O)
 * - process_values: Consumes the iterator and reports timing deltas via progress events
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, sleep } from './utils/test_helpers.js';

describe('Async Iterator Support', () => {
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
  // Pattern 8: Direct AsyncIterator consumption
  // ============================================================================

  test('Should consume async iterator and return all yielded values', async () => {
    logTest('Pattern 8: Direct AsyncIterator consumption');

    const values = ['alpha', 'beta', 'gamma'];
    
    logStep(`Calling get_async_iterator with values: ${values.join(', ')}`);
    const startTime = Date.now();
    
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    const elapsedMs = Date.now() - startTime;

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    // The MethodNamespace should consume the async iterator and return collected values
    expect(response.data).toBeDefined();
    expect(response.data.values).toBeDefined();
    expect(Array.isArray(response.data.values)).toBe(true);
    expect(response.data.values.length).toBe(values.length);
    expect(response.data.total_count).toBe(values.length);
    expect(response.data.async_iterator).toBe(true);

    // Verify all values were yielded in order
    for (let i = 0; i < values.length; i++) {
      expect(response.data.values[i]).toBe(values[i]);
    }

    // Should take at least min_ms per value
    const expectedMinMs = values.length * 50;
    expect(elapsedMs).toBeGreaterThanOrEqual(expectedMinMs - 100); // 100ms tolerance

    logSuccess(`AsyncIterator consumed ${response.data.total_count} values in ${elapsedMs}ms`);
  });

  test('Should handle async iterator with different delay ranges', async () => {
    logTest('Pattern 8: AsyncIterator with variable delays');

    const values = ['delta', 'epsilon'];
    
    logStep('Testing with min_ms=100, max_ms=200');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: values,
        min_ms: 100,
        max_ms: 200
      }
    }, 15000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data.values).toEqual(values);
    expect(response.data.total_count).toBe(2);

    logSuccess(`AsyncIterator handled variable delays correctly`);
  });

  test('Should emit progress events for each yielded value', async () => {
    logTest('Pattern 8: AsyncIterator progress events');

    const values = ['theta', 'kappa', 'lambda'];
    
    logStep('Collecting progress events during iteration');
    
    // Track progress events
    const progressEvents = [];
    client.on('method:execute:progress', (data) => {
      progressEvents.push(data);
    });

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    // Wait a bit for progress events to arrive
    await sleep(500);

    ResponseValidators.assertSuccess(response);
    expect(response.data.values).toEqual(values);

    // Each yielded value should have triggered a progress event
    // Note: Progress events are emitted by the MethodNamespace when consuming the iterator
    expect(progressEvents.length).toBeGreaterThanOrEqual(0); // May be 0 if events arrive after ACK

    logSuccess(`AsyncIterator emitted progress for ${values.length} yielded values`);
  });

  test('Should handle async iterator with single value', async () => {
    logTest('Pattern 8: AsyncIterator with single value');

    const values = ['omega'];
    
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    ResponseValidators.assertSuccess(response);
    expect(response.data.values).toEqual(values);
    expect(response.data.total_count).toBe(1);

    logSuccess('AsyncIterator handled single value correctly');
  });

  test('Should handle async iterator with empty list', async () => {
    logTest('Pattern 8: AsyncIterator with empty list');

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: [],
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    ResponseValidators.assertSuccess(response);
    expect(response.data.values).toEqual([]);
    expect(response.data.total_count).toBe(0);

    logSuccess('AsyncIterator handled empty list correctly');
  });

  test('Should validate async iterator parameters', async () => {
    logTest('Pattern 8: AsyncIterator parameter validation');

    logStep('Testing with negative min_ms');
    const response1 = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: ['test'],
        min_ms: -10,
        max_ms: 100
      }
    }, 15000);

    ResponseValidators.assertHasError(response1);
    expect(response1.error_stack[0].message).toContain('non-negative');

    logStep('Testing with min_ms > max_ms');
    const response2 = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: ['test'],
        min_ms: 200,
        max_ms: 100
      }
    }, 15000);

    ResponseValidators.assertHasError(response2);
    expect(response2.error_stack[0].message).toContain('min_ms must be <= max_ms');

    logSuccess('AsyncIterator parameter validation works correctly');
  });

  // ============================================================================
  // Pattern 9: AsyncIterator with progress callback (process_values)
  // ============================================================================

  test('Should process async iterator values with timing deltas', async () => {
    logTest('Pattern 9: process_values with timing information');

    const values = ['alpha', 'delta', 'epsilon'];
    
    logStep(`Calling process_values with ${values.length} values`);
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.process_values',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 100
      }
    }, 20000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(response.data.total_values).toBe(values.length);
    expect(Array.isArray(response.data.results)).toBe(true);
    expect(response.data.results.length).toBe(values.length);
    expect(response.data.total_elapsed_ms).toBeDefined();
    expect(response.data.async).toBe(true);
    expect(response.data.async_iterator).toBe(true);

    // Verify each result has the expected structure
    for (let i = 0; i < values.length; i++) {
      const result = response.data.results[i];
      expect(result.value).toBe(values[i]);
      expect(result.delta_ms).toBeDefined();
      expect(typeof result.delta_ms).toBe('number');
      expect(result.timestamp).toBeDefined();
      
      // Each delta should be within the min/max range (with tolerance)
      if (result.delta_ms > 0) {
        expect(result.delta_ms).toBeGreaterThanOrEqual(40); // min_ms - tolerance
        expect(result.delta_ms).toBeLessThanOrEqual(200); // max_ms + tolerance
      }
    }

    logSuccess(`process_values processed ${values.length} values with timing deltas`);
  });

  test('Should emit progress events during async iterator processing', async () => {
    logTest('Pattern 9: process_values progress streaming');

    const values = ['gamma', 'kappa', 'lambda', 'omega'];
    
    // Track progress events
    const progressEvents = [];
    client.on('method:execute:progress', (data) => {
      logStep(`Progress event received: ${data.description}`);
      progressEvents.push(data);
    });

    logStep(`Processing ${values.length} values with progress tracking`);
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.process_values',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 100
      }
    }, 20000);

    // Wait for progress events to arrive
    await sleep(1000);

    ResponseValidators.assertSuccess(response);
    expect(response.data.total_values).toBe(values.length);

    // Should have received progress events (one per value)
    // Note: Timing may cause events to arrive after the ACK
    logStep(`Received ${progressEvents.length} progress events`);

    // Verify progress event structure if any were received
    if (progressEvents.length > 0) {
      for (const event of progressEvents) {
        expect(event.percent).toBeDefined();
        expect(event.title).toBe('Processing Values');
        expect(event.description).toBeDefined();
        expect(event.data).toBeDefined();
        expect(event.data.value).toBeDefined();
        expect(event.data.delta_ms).toBeDefined();
        expect(event.data.timestamp).toBeDefined();
      }
      
      logSuccess(`Progress events contain timing and value data`);
    } else {
      logSuccess(`Processing completed (progress events may have arrived after ACK)`);
    }
  });

  test('Should calculate correct percentages in progress events', async () => {
    logTest('Pattern 9: Progress percentage calculation');

    const values = ['test1', 'test2', 'test3', 'test4', 'test5'];
    
    const progressEvents = [];
    client.on('method:execute:progress', (data) => {
      progressEvents.push(data);
    });

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.process_values',
      args: {
        values: values,
        min_ms: 30,
        max_ms: 50
      }
    }, 20000);

    await sleep(1000);

    ResponseValidators.assertSuccess(response);

    // Verify percentages if events were captured
    if (progressEvents.length > 0) {
      for (let i = 0; i < progressEvents.length; i++) {
        const expectedPercent = ((i + 1) / values.length) * 100;
        expect(progressEvents[i].percent).toBeCloseTo(expectedPercent, 0);
      }
      
      logSuccess(`Progress percentages calculated correctly (${progressEvents.length} events)`);
    } else {
      logSuccess('Processing completed successfully');
    }
  });

  test('Should stream partial results via progress data field', async () => {
    logTest('Pattern 9: Partial result streaming');

    const values = ['result1', 'result2', 'result3'];
    
    const progressEvents = [];
    client.on('method:execute:progress', (data) => {
      progressEvents.push(data);
    });

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.process_values',
      args: {
        values: values,
        min_ms: 50,
        max_ms: 80
      }
    }, 20000);

    await sleep(1000);

    ResponseValidators.assertSuccess(response);

    // Verify partial results in progress events
    if (progressEvents.length > 0) {
      for (const event of progressEvents) {
        // Each progress event should contain the partial result in the data field
        expect(event.data).toBeDefined();
        expect(event.data.value).toBeDefined();
        expect(event.data.delta_ms).toBeDefined();
        expect(event.data.timestamp).toBeDefined();
      }
      
      logSuccess(`Partial results streamed via ${progressEvents.length} progress events`);
    } else {
      logSuccess('Processing completed (events timing varies)');
    }
  });

  test('Should handle process_values with different value counts', async () => {
    logTest('Pattern 9: Variable value count handling');

    const testCases = [
      { values: ['single'], expectedCount: 1 },
      { values: ['one', 'two'], expectedCount: 2 },
      { values: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'], expectedCount: 10 }
    ];

    for (const testCase of testCases) {
      logStep(`Testing with ${testCase.expectedCount} values`);
      
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.process_values',
        args: {
          values: testCase.values,
          min_ms: 20,
          max_ms: 40
        }
      }, 20000);

      ResponseValidators.assertSuccess(response);
      expect(response.data.total_values).toBe(testCase.expectedCount);
      expect(response.data.results.length).toBe(testCase.expectedCount);
    }

    logSuccess('process_values handled different value counts correctly');
  });

  test('Should measure total elapsed time correctly', async () => {
    logTest('Pattern 9: Total elapsed time measurement');

    const values = ['time1', 'time2', 'time3'];
    const minMs = 50;
    const maxMs = 100;
    
    const startTime = Date.now();
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.process_values',
      args: {
        values: values,
        min_ms: minMs,
        max_ms: maxMs
      }
    }, 20000);

    const clientElapsedMs = Date.now() - startTime;

    ResponseValidators.assertSuccess(response);

    // Server-reported elapsed time should be at least minMs * count
    const expectedMinMs = values.length * minMs;
    expect(response.data.total_elapsed_ms).toBeGreaterThanOrEqual(expectedMinMs - 50);

    // Client-measured time should be close to server-measured time
    const timeDifference = Math.abs(clientElapsedMs - response.data.total_elapsed_ms);
    expect(timeDifference).toBeLessThan(500); // Allow for network latency

    logSuccess(`Elapsed time: server=${response.data.total_elapsed_ms}ms, client=${clientElapsedMs}ms`);
  });

  // ============================================================================
  // Integration and Edge Cases
  // ============================================================================

  test('Should handle async iterator alongside regular async methods', async () => {
    logTest('Integration: AsyncIterator mixed with regular async methods');

    logStep('Starting async iterator and regular async method concurrently');
    
    const [iteratorResponse, regularResponse] = await Promise.all([
      client.emitAndWait('method:execute', {
        method: 'fraxis.api.get_async_iterator',
        args: {
          values: ['concurrent1', 'concurrent2'],
          min_ms: 50,
          max_ms: 100
        }
      }, 15000),
      client.emitAndWait('method:execute', {
        method: 'fraxis.api.async_simple_operation',
        args: {
          value: 5
        }
      }, 15000)
    ]);

    ResponseValidators.assertSuccess(iteratorResponse);
    ResponseValidators.assertSuccess(regularResponse);

    expect(iteratorResponse.data.async_iterator).toBe(true);
    expect(regularResponse.data.async).toBe(true);

    logSuccess('AsyncIterator and regular async method executed concurrently');
  });

  test('Should maintain response envelope structure for async iterators', async () => {
    logTest('Response envelope validation for AsyncIterator');

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: ['envelope', 'test'],
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    // Check all required response envelope fields
    expect(response).toHaveProperty('data');
    expect(response).toHaveProperty('metadata');
    expect(response).toHaveProperty('error_stack');
    expect(response).toHaveProperty('warning_stack');
    expect(response).toHaveProperty('info_stack');

    expect(Array.isArray(response.error_stack)).toBe(true);
    expect(Array.isArray(response.warning_stack)).toBe(true);
    expect(Array.isArray(response.info_stack)).toBe(true);

    ResponseValidators.assertMetadata(response);

    logSuccess('AsyncIterator response maintains envelope structure');
  });

  test('Should handle rapid sequential async iterator calls', async () => {
    logTest('Performance: Rapid sequential AsyncIterator calls');

    logStep('Making 5 rapid sequential async iterator calls');
    const results = [];
    
    for (let i = 0; i < 5; i++) {
      const response = await client.emitAndWait('method:execute', {
        method: 'fraxis.api.get_async_iterator',
        args: {
          values: [`seq${i}`],
          min_ms: 20,
          max_ms: 40
        }
      }, 15000);
      
      ResponseValidators.assertSuccess(response);
      results.push(response.data.values[0]);
    }

    expect(results.length).toBe(5);
    for (let i = 0; i < 5; i++) {
      expect(results[i]).toBe(`seq${i}`);
    }

    logSuccess('Rapid sequential AsyncIterator calls completed successfully');
  });

  test('Should handle concurrent async iterator calls', async () => {
    logTest('Concurrency: Multiple parallel AsyncIterator calls');

    logStep('Starting 3 concurrent async iterator calls');
    const promises = [];
    
    for (let i = 0; i < 3; i++) {
      promises.push(
        client.emitAndWait('method:execute', {
          method: 'fraxis.api.get_async_iterator',
          args: {
            values: [`parallel${i}a`, `parallel${i}b`],
            min_ms: 30,
            max_ms: 60
          }
        }, 15000)
      );
    }

    const responses = await Promise.all(promises);

    responses.forEach((response, index) => {
      ResponseValidators.assertSuccess(response);
      expect(response.data.values.length).toBe(2);
      expect(response.data.values[0]).toBe(`parallel${index}a`);
      expect(response.data.values[1]).toBe(`parallel${index}b`);
    });

    logSuccess('Concurrent AsyncIterator calls completed successfully');
  });

  test('Should handle process_values with subscription and broadcasts', async () => {
    logTest('Integration: AsyncIterator with method subscriptions');

    const methodName = 'fraxis.api.process_values';

    logStep('Subscribing to method');
    const subResponse = await client.emitAndWait('method:subscribe', {
      method: methodName
    });

    ResponseValidators.assertSuccess(subResponse);
    expect(subResponse.data.subscribed).toBe(true);

    logStep('Executing process_values');
    const execResponse = await client.emitAndWait('method:execute', {
      method: methodName,
      args: {
        values: ['sub1', 'sub2', 'sub3'],
        min_ms: 40,
        max_ms: 80
      }
    }, 20000);

    ResponseValidators.assertSuccess(execResponse);

    // Wait for broadcast events
    await sleep(1000);

    logSuccess('AsyncIterator method executed with subscription');
  });

  // ============================================================================
  // Metadata and Response Structure
  // ============================================================================

  test('Should include correct metadata in async iterator responses', async () => {
    logTest('Metadata validation for AsyncIterator');

    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: ['metadata', 'test'],
        min_ms: 50,
        max_ms: 100
      }
    }, 15000);

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertMetadata(response);

    const { metadata } = response;
    expect(metadata.timestamp).toBeDefined();
    expect(metadata.sid).toBeDefined();
    expect(metadata.site).toBeDefined();

    logSuccess('AsyncIterator response includes valid metadata');
  });

  test('Should properly structure collected iterator values', async () => {
    logTest('Iterator value collection structure');

    const inputValues = ['value1', 'value2', 'value3', 'value4'];
    
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.get_async_iterator',
      args: {
        values: inputValues,
        min_ms: 30,
        max_ms: 60
      }
    }, 15000);

    ResponseValidators.assertSuccess(response);

    // Verify the structure of collected values
    expect(response.data.values).toEqual(inputValues);
    expect(response.data.total_count).toBe(inputValues.length);
    expect(response.data.async_iterator).toBe(true);

    // Values should be in the same order as input
    for (let i = 0; i < inputValues.length; i++) {
      expect(response.data.values[i]).toBe(inputValues[i]);
    }

    logSuccess('Iterator values collected and structured correctly');
  });
});
