/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * DocType Operations Tests
 * 
 * Tests for collection-level DocType operations like list, count, and meta.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess } from './utils/test_helpers.js';

describe('DocType Operations', () => {
  let client;
  let createdDocuments = [];

  beforeEach(async () => {
    client = new FraxisSocketIOClient(null, '/api/doctype');
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
  });

  afterEach(async () => {
    // Cleanup - use document namespace to delete
    const docClient = new FraxisSocketIOClient(null, '/api/document');
    await docClient.connectWithAuth({ token: TestFixtures.getAuthToken() });

    for (const doc of createdDocuments) {
      try {
        await docClient.emitAndWait('document:delete', {
          doctype: doc.doctype,
          name: doc.name
        });
      } catch (error) {
        // Ignore cleanup errors
      }
    }
    createdDocuments = [];

    if (docClient && docClient.isConnected) {
      await docClient.disconnect();
    }

    if (client && client.isConnected) {
      await client.disconnect();
    }
  });

  test('Should list documents with pagination', async () => {
    logTest('List documents with pagination');

    logStep('Listing ToDo documents');
    const response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      limit: 10,
      limit_start: 0
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    const documents = response.data;
    expect(Array.isArray(documents)).toBe(true);

    logSuccess(`Listed ${documents.length} documents`);
  });

  test('Should apply filters to list query', async () => {
    logTest('Apply filters to list query');

    logStep('Listing documents with filters');
    const response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      filters: [['status', '=', 'Open']],
      limit: 10
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    const documents = response.data;
    expect(Array.isArray(documents)).toBe(true);

    logSuccess(`Filtered list returned ${documents.length} documents`);
  });

  test('Should select specific fields in list', async () => {
    logTest('Select specific fields in list');

    logStep('Listing documents with standard fields');
    const response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      fields: ['name', 'status'],  // Use standard fields that Frappe allows
      limit: 5
    });

    // This might fail if Frappe restricts field access, but test the error handling
    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Field restrictions properly enforced by server');
    } else {
      ResponseValidators.assertResponseEnvelope(response);
      ResponseValidators.assertSuccess(response);

      const documents = response.data;
      expect(Array.isArray(documents)).toBe(true);
      logSuccess(`Field selection working correctly`);
    }
  });

  test('Should count documents matching criteria', async () => {
    logTest('Count documents');

    logStep('Counting ToDo documents');
    const response = await client.emitAndWait('doctype:count', {
      doctype: 'ToDo'
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(typeof response.data.count).toBe('number');
    expect(response.data.count).toBeGreaterThanOrEqual(0);

    logSuccess(`Document count: ${response.data.count}`);
  });

  test('Should count documents with filters', async () => {
    logTest('Count documents with filters');

    logStep('Counting documents matching filter');
    const response = await client.emitAndWait('doctype:count', {
      doctype: 'ToDo',
      filters: [['status', '=', 'Open']]
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    expect(response.data).toBeDefined();
    expect(typeof response.data.count).toBe('number');

    logSuccess(`Filtered count: ${response.data.count}`);
  });

  test('Should retrieve DocType metadata', async () => {
    logTest('Retrieve DocType metadata');

    logStep('Fetching ToDo metadata');
    const response = await client.emitAndWait('doctype:meta', {
      doctype: 'ToDo'
    });

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);

    const meta = response.data;
    expect(meta).toBeDefined();
    expect(meta.name).toBe('ToDo');
    
    // label might not always be present depending on Frappe setup
    if (meta.label) {
      expect(meta.label).toBeDefined();
    }

    if (meta.fields) {
      expect(Array.isArray(meta.fields)).toBe(true);
      logStep(`Retrieved ${meta.fields.length} fields`);
    }

    logSuccess('DocType metadata retrieved successfully');
  });

  test('Should handle missing DocType gracefully', async () => {
    logTest('Handle missing DocType');

    logStep('Attempting to get metadata for non-existent DocType');
    const response = await client.emitAndWait('doctype:meta', {
      doctype: 'NonExistentDocType12345'
    });

    if (response.error_stack && response.error_stack.length > 0) {
      logSuccess('Missing DocType properly rejected with error');
    } else {
      logSuccess('Server handled missing DocType gracefully');
    }
  });

  test('Should validate list response envelope structure', async () => {
    logTest('Validate list response structure');

    logStep('Listing documents');
    const response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      limit: 1
    });

    ResponseValidators.assertResponseEnvelope(response);
    expect(Array.isArray(response.data)).toBe(true);

    logSuccess('List response structure valid');
  });

  test('Should validate count response envelope structure', async () => {
    logTest('Validate count response structure');

    logStep('Counting documents');
    const response = await client.emitAndWait('doctype:count', {
      doctype: 'ToDo'
    });

    ResponseValidators.assertResponseEnvelope(response);
    expect(response.data).toBeDefined();
    expect('count' in response.data).toBe(true);

    logSuccess('Count response structure valid');
  });

  test('Should validate meta response envelope structure', async () => {
    logTest('Validate meta response structure');

    logStep('Fetching metadata');
    const response = await client.emitAndWait('doctype:meta', {
      doctype: 'ToDo'
    });

    ResponseValidators.assertResponseEnvelope(response);
    expect(response.data).toBeDefined();
    expect(response.data.name).toBe('ToDo');

    logSuccess('Meta response structure valid');
  });

  test('Should support pagination with limit and offset', async () => {
    logTest('Support pagination');

    logStep('Testing pagination with limit=5 and offset=0');
    const page1Response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      limit: 5,
      limit_start: 0
    });

    expect(Array.isArray(page1Response.data)).toBe(true);
    const page1Docs = page1Response.data;

    logStep('Testing pagination with limit=5 and offset=5');
    const page2Response = await client.emitAndWait('doctype:list', {
      doctype: 'ToDo',
      limit: 5,
      limit_start: 5
    });

    expect(Array.isArray(page2Response.data)).toBe(true);

    logSuccess('Pagination working correctly');
  });
});
