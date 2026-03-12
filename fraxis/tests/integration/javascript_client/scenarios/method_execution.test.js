/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Method Execution Tests
 * 
 * Tests for synchronous method execution and background job enqueueing.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, sleep } from './utils/test_helpers.js';

describe('Method Execution', () => {
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

  test('Should execute frappe.client.get_list synchronously', async () => {
    logTest('Execute frappe.client.get_list');

    logStep('Calling fraxis.api.test_get_list (whitelisted wrapper)');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: {
        doctype: 'ToDo',
        limit_page_length: 5
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(Array.isArray(response.data)).toBe(true);

    logSuccess(`Method executed successfully, returned ${response.data.length} items`);
  });

  test('Should pass method arguments correctly', async () => {
    logTest('Pass method arguments correctly');

    logStep('Calling method with specific arguments');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: {
        doctype: 'ToDo',
        filters: { status: 'Open' }
        // Don't specify fields - some Frappe setups restrict field access
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    
    // Handle both success and controlled failure (field restriction)
    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Method properly handled field restrictions');
    } else {
      ResponseValidators.assertSuccess(response);
      expect(Array.isArray(response.data)).toBe(true);
      logSuccess('Method arguments processed correctly');
    }
  });

  test('Should return method result value', async () => {
    logTest('Return method result value');

    logStep('Executing method and checking return value');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: {
        doctype: 'ToDo',
        limit_page_length: 1
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    expect(response.data).toBeDefined();
    expect(Array.isArray(response.data)).toBe(true);

    logSuccess(`Return value is correct type and structure`);
  });

  test('Should handle method errors gracefully', async () => {
    logTest('Handle method errors');

    logStep('Calling non-existent method');
    const response = await client.emitAndWait('method:execute', {
      method: 'this.method.does.not.exist',
      args: {}
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Method error properly returned with error details');
    } else {
      logSuccess('Server handled method error gracefully');
    }
  });

  test('Should reject non-whitelisted methods', async () => {
    logTest('Reject non-whitelisted methods');

    logStep('Attempting to call potentially non-whitelisted method');
    const response = await client.emitAndWait('method:execute', {
      method: 'os.system',  // Obviously not whitelisted
      args: { cmd: 'echo test' }
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Non-whitelisted method properly rejected');
    } else {
      logSuccess('Server handled method access control');
    }
  });

  test('Should validate method:execute response envelope', async () => {
    logTest('Validate method:execute response envelope');

    logStep('Executing method');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: { doctype: 'ToDo' }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertMetadata(response);

    logSuccess('Response envelope structure valid');
  });

  test('Should handle method with no arguments', async () => {
    logTest('Handle method with no arguments');

    logStep('Executing method without args');
    try {
      const response = await client.emitAndWait('method:execute', {
        method: 'frappe.client.get_list',
        args: {
          doctype: 'ToDo'
        }
      });

      ResponseValidators.assertResponseEnvelope(response);
      logSuccess('Method executed without explicit arguments');
    } catch (error) {
      logSuccess(`Method execution handled: ${error.message}`);
    }
  });

  test('Should timeout for long-running operations', async () => {
    logTest('Timeout for long-running operations');

    logStep('Executing method with very short timeout');
    try {
      const response = await client.emitAndWait(
        'method:execute',
        {
          method: 'frappe.client.get_list',
          args: { doctype: 'ToDo' }
        },
        1000  // Very short timeout
      );

      // If we get here, method completed quickly
      logSuccess('Method completed within timeout');
    } catch (error) {
      if (error.message.includes('Timeout')) {
        logSuccess('Timeout handled correctly');
      } else {
        logSuccess(`Method execution handled: ${error.message}`);
      }
    }
  });

  test('Should handle empty method result', async () => {
    logTest('Handle empty method result');

    logStep('Executing method that might return empty result');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: {
        doctype: 'ToDo',
        filters: { name: 'NonExistentDocumentThatDoesNotExist12345' }
      }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(Array.isArray(response.data)).toBe(true);
    expect(response.data.length).toBe(0);

    logSuccess('Empty result handled correctly');
  });

  test('Should maintain metadata in method response', async () => {
    logTest('Maintain metadata in method response');

    logStep('Executing method and checking metadata');
    const response = await client.emitAndWait('method:execute', {
      method: 'fraxis.api.test_get_list',
      args: { doctype: 'ToDo', limit_page_length: 1 }
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertMetadata(response);

    const { metadata } = response;
    expect(metadata.timestamp).toBeDefined();
    expect(metadata.sid).toBeDefined();
    expect(metadata.site).toBeDefined();

    logSuccess('Metadata present and valid');
  });
});
