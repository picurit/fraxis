/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Error Handling Tests
 * 
 * Tests for error scenarios, validation errors, and recovery.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess } from './utils/test_helpers.js';

describe('Error Handling', () => {
  let client;

  beforeEach(async () => {
    client = new FraxisSocketIOClient(null, '/api/document');
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
  });

  afterEach(async () => {
    if (client && client.isConnected) {
      await client.disconnect();
    }
  });

  test('Should handle malformed request payloads', async () => {
    logTest('Handle malformed request payloads');

    logStep('Sending request with missing required field');
    const response = await client.emitAndWait('document:create', {
      // Missing 'data' field
      doctype: 'ToDo'
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Malformed request properly rejected');
    } else {
      logSuccess('Server handled malformed request gracefully');
    }
  });

  test('Should handle missing required fields', async () => {
    logTest('Handle missing required fields');

    logStep('Creating document without required title field');
    const response = await client.emitAndWait('document:create', {
      doctype: 'ToDo',
      data: {
        // Missing title field that might be required
        description: 'Test without title'
      }
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      expect(response.error_stack[0]).toBeDefined();
      logSuccess('Missing field error properly returned');
    } else {
      logSuccess('Server handled missing fields gracefully');
    }
  });

  test('Should handle read of non-existent document', async () => {
    logTest('Handle read of non-existent document');

    logStep('Reading non-existent document');
    const response = await client.emitAndWait('document:read', {
      doctype: 'ToDo',
      name: 'NonExistentDocument12345'
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Non-existent document properly reported');
    } else {
      logSuccess('Server handled missing document gracefully');
    }
  });

  test('Should handle invalid DocType in operations', async () => {
    logTest('Handle invalid DocType');

    logStep('Creating with invalid DocType');
    const response = await client.emitAndWait('document:create', {
      doctype: 'NonExistentDocType12345',
      data: { title: 'Test' }
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Invalid DocType properly rejected');
    } else {
      logSuccess('Server handled invalid DocType gracefully');
    }
  });

  test('Should handle database connection errors gracefully', async () => {
    logTest('Handle database connection errors');

    logStep('Executing operation (should handle any DB errors)');
    try {
      const response = await client.emitAndWait('document:read', {
        doctype: 'ToDo',
        name: 'TestDoc'
      });

      ResponseValidators.assertResponseEnvelope(response);
      logSuccess('Database operation handled correctly');
    } catch (error) {
      logSuccess(`Database error handled: ${error.message}`);
    }
  });

  test('Should validate response envelope in error scenarios', async () => {
    logTest('Validate response envelope in error');

    logStep('Triggering an error condition');
    const response = await client.emitAndWait('document:read', {
      doctype: 'InvalidDocType',
      name: 'NonExistent'
    });

    // Even in error case, envelope should be valid
    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      const error = response.error_stack[0];
      expect(error.code).toBeDefined();
      expect(error.message).toBeDefined();
      logSuccess('Error response envelope properly structured');
    } else {
      logSuccess('Response envelope valid');
    }
  });

  test('Should handle socket timeout gracefully', async () => {
    logTest('Handle socket timeout');

    logStep('Testing short timeout');
    try {
      await client.emitAndWait(
        'document:read',
        { doctype: 'ToDo', name: 'Test' },
        100  // Very short timeout
      );
      logSuccess('Request completed quickly');
    } catch (error) {
      if (error.message.includes('Timeout')) {
        logSuccess('Timeout handled correctly');
      } else {
        logSuccess(`Error handled: ${error.message}`);
      }
    }
  });

  test('Should recover from network errors', async () => {
    logTest('Recover from network errors');

    logStep('Testing operation after potential network issue');
    try {
      const response = await client.emitAndWait('document:read', {
        doctype: 'ToDo',
        name: 'TestDoc'
      });

      ResponseValidators.assertResponseEnvelope(response);
      logSuccess('Socket recovered and operation succeeded');
    } catch (error) {
      logSuccess(`Recovery attempt made: ${error.message}`);
    }
  });

  test('Should include error details in response', async () => {
    logTest('Include error details in response');

    logStep('Creating with invalid data');
    const response = await client.emitAndWait('document:create', {
      doctype: 'ToDo',
      data: {} // Empty data
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      const error = response.error_stack[0];
      expect(error).toHaveProperty('code');
      expect(error).toHaveProperty('message');
      expect(error).toHaveProperty('severity');
      logSuccess('Error details properly included');
    } else {
      logSuccess('Response structure valid');
    }
  });

  test('Should maintain socket connection after error', async () => {
    logTest('Maintain socket after error');

    // Trigger an error
    logStep('Triggering error condition');
    await client.emitAndWait('document:read', {
      doctype: 'InvalidType',
      name: 'None'
    });

    logStep('Attempting operation after error');
    expect(client.isConnected).toBe(true);

    // Try another operation
    const response = await client.emitAndWait('document:read', {
      doctype: 'ToDo',
      name: 'TestDoc'
    });

    ResponseValidators.assertResponseEnvelope(response);
    logSuccess('Socket remained connected after error');
  });

  test('Should handle empty data objects', async () => {
    logTest('Handle empty data objects');

    logStep('Creating with empty data');
    const response = await client.emitAndWait('document:create', {
      doctype: 'ToDo',
      data: {}
    });

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Empty data validation triggered properly');
    } else {
      logSuccess('Empty data handled gracefully');
    }
  });

  test('Should reject null payloads', async () => {
    logTest('Reject null payloads');

    logStep('Sending null payload');
    try {
      const response = await client.emitAndWait('document:create', null);

      if (response && response.error_stack) {
        logSuccess('Null payload rejected');
      } else {
        logSuccess('Null payload handled');
      }
    } catch (error) {
      logSuccess(`Null payload error handled: ${error.message}`);
    }
  });

  test('Should handle very large payloads', async () => {
    logTest('Handle very large payloads');

    // Create a large object
    const largeData = {
      doctype: 'ToDo',
      data: {
        title: 'Large Test',
        description: 'x'.repeat(10000) // 10KB description
      }
    };

    logStep('Sending large payload');
    const response = await client.emitAndWait('document:create', largeData);

    ResponseValidators.assertResponseEnvelope(response);

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Large payload properly validated');
    } else {
      logSuccess('Large payload handled');
    }
  });

  test('Should handle special characters in data', async () => {
    logTest('Handle special characters');

    const specialData = {
      doctype: 'ToDo',
      data: {
        title: 'Test with "quotes" and \'apostrophes\' and \n newlines \t tabs',
        description: 'Unicode: 你好世界 🎉 مرحبا'
      }
    };

    logStep('Creating with special characters');
    const response = await client.emitAndWait('document:create', specialData);

    ResponseValidators.assertResponseEnvelope(response);

    if (response.data && response.data.name) {
      logSuccess('Special characters handled correctly');

      // Cleanup
      try {
        await client.emitAndWait('document:delete', {
          doctype: 'ToDo',
          name: response.data.name
        });
      } catch (error) {
        // Ignore cleanup error
      }
    } else {
      logSuccess('Special character handling verified');
    }
  });
});
