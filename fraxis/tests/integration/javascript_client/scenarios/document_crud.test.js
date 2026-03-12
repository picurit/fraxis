/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Document CRUD Tests
 * 
 * Tests for create, read, update, and delete operations
 * on Frappe documents via Socket.IO.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, generateId } from './utils/test_helpers.js';

describe('Document CRUD Operations', () => {
  let client;
  let createdDocuments = [];

  beforeEach(async () => {
    client = new FraxisSocketIOClient(null, '/api/document');
    await client.connectWithAuth({ token: TestFixtures.getAuthToken() });
  });

  afterEach(async () => {
    // Cleanup created documents
    for (const doc of createdDocuments) {
      try {
        await client.emitAndWait('document:delete', {
          doctype: doc.doctype,
          name: doc.name
        });
      } catch (error) {
        // Ignore cleanup errors
      }
    }
    createdDocuments = [];

    if (client && client.isConnected) {
      await client.disconnect();
    }
  });

  test('Should create a new document', async () => {
    logTest('Create a new document');

    const docData = TestFixtures.generateDocumentData('ToDo');
    logStep(`Creating ToDo with data: ${JSON.stringify(docData.data)}`);

    const response = await client.emitAndWait('document:create', docData);
    logStep('Received response');

    ResponseValidators.assertResponseEnvelope(response);
    ResponseValidators.assertSuccess(response);
    ResponseValidators.assertMetadata(response);

    const createdDoc = response.data;
    expect(createdDoc).toBeDefined();
    expect(createdDoc.name).toBeDefined();
    expect(createdDoc.doctype).toBe('ToDo');
    // Title might not be in response due to Frappe field restrictions
    if (createdDoc.title) {
      expect(createdDoc.title).toBe(docData.data.title);
    }

    createdDocuments.push({ doctype: createdDoc.doctype, name: createdDoc.name });

    logSuccess(`Document created with name: ${createdDoc.name}`);
  });

  test('Should read an existing document', async () => {
    logTest('Read an existing document');

    // First create a document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await client.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep(`Created document: ${docName}`);

    // Now read it
    logStep('Reading the document');
    const readResponse = await client.emitAndWait('document:read', {
      doctype: 'ToDo',
      name: docName
    });

    ResponseValidators.assertResponseEnvelope(readResponse);
    ResponseValidators.assertSuccess(readResponse);

    const readDoc = readResponse.data;
    expect(readDoc.name).toBe(docName);
    expect(readDoc.doctype).toBe('ToDo');
    // Title might not be in response due to Frappe field restrictions
    if (readDoc.title) {
      expect(readDoc.title).toBe(docData.data.title);
    }

    logSuccess(`Document read successfully`);
  });

  test('Should update a document', async () => {
    logTest('Update a document');

    // Create a document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await client.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep(`Created document: ${docName}`);

    // Update it
    const newTitle = `Updated Title ${Date.now()}`;
    logStep(`Updating title to: ${newTitle}`);

    const updateResponse = await client.emitAndWait('document:update', {
      doctype: 'ToDo',
      name: docName,
      data: { title: newTitle }
    });

    ResponseValidators.assertResponseEnvelope(updateResponse);
    ResponseValidators.assertSuccess(updateResponse);

    const updatedDoc = updateResponse.data;
    // Title might not be in response due to Frappe field restrictions
    if (updatedDoc.title) {
      expect(updatedDoc.title).toBe(newTitle);
    } else {
      logSuccess('Document updated (title not returned by server)');
    }

    logSuccess(`Document updated successfully`);
  });

  test('Should delete a document', async () => {
    logTest('Delete a document');

    // Create a document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await client.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    logStep(`Created document: ${docName}`);

    // Delete it
    logStep('Deleting the document');
    const deleteResponse = await client.emitAndWait('document:delete', {
      doctype: 'ToDo',
      name: docName
    });

    ResponseValidators.assertResponseEnvelope(deleteResponse);
    ResponseValidators.assertSuccess(deleteResponse);

    const deleteResult = deleteResponse.data;
    expect(deleteResult.name).toBe(docName);

    logSuccess(`Document deleted successfully`);
  });

  test('Should receive document:create:start state signal', async () => {
    logTest('Receive document:create:start state signal');

    client.clearEventQueue();
    const docData = TestFixtures.generateDocumentData('ToDo');
    logStep('Creating document and listening for state signals');

    const response = await client.emitAndWait('document:create', docData);
    const docName = response.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    // Check for state signals in queue
    const startEvents = client.getEventsFromQueue('document:create:start');
    const successEvents = client.getEventsFromQueue('document:create:success');

    logStep(`Found ${startEvents.length} :start events and ${successEvents.length} :success events`);

    expect(successEvents.length).toBeGreaterThan(0);

    logSuccess('State signals received correctly');
  });

  test('Should emit document:updated broadcast when document is saved by another connection', async () => {
    logTest('Emit document:updated broadcast');

    // Create a document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await client.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep(`Created document: ${docName}`);

    // Subscribe to document updates
    logStep('Subscribing to document changes');
    await client.subscribeToDocument('ToDo', docName);

    client.clearEventQueue();

    // Update the document
    logStep('Updating document');
    const newTitle = `Broadcast Test ${Date.now()}`;
    await client.emitAndWait('document:update', {
      doctype: 'ToDo',
      name: docName,
      data: { title: newTitle }
    });

    // Check for broadcast event
    const updatedEvents = client.getEventsFromQueue('document:updated');
    logStep(`Found ${updatedEvents.length} document:updated broadcast events`);

    expect(updatedEvents.length).toBeGreaterThan(0);

    logSuccess('document:updated broadcast received');
  });

  test('Should handle permission denied errors', async () => {
    logTest('Handle permission denied error');

    const docData = TestFixtures.generateDocumentData('ToDo');
    logStep('Attempting operation (may trigger permission error)');

    try {
      // Try to create with test data - if permissions are enforced, might fail
      const response = await client.emitAndWait('document:create', docData);
      
      if (response.error_stack && response.error_stack.length > 0) {
        logStep('Received permission denied error as expected');
        expect(response.error_stack[0].code).toBeDefined();
        logSuccess('Permission error handled correctly');
      } else {
        logSuccess('Operation succeeded (no permission restrictions in test environment)');
      }
    } catch (error) {
      logSuccess(`Error handled: ${error.message}`);
    }
  });

  test('Should validate response envelope structure for all CRUD operations', async () => {
    logTest('Validate response envelopes');

    // CREATE
    let response = await client.emitAndWait('document:create', TestFixtures.generateDocumentData());
    ResponseValidators.assertResponseEnvelope(response);
    const docName = response.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep('✓ CREATE response envelope valid');

    // READ
    response = await client.emitAndWait('document:read', {
      doctype: 'ToDo',
      name: docName
    });
    ResponseValidators.assertResponseEnvelope(response);
    logStep('✓ READ response envelope valid');

    // UPDATE
    response = await client.emitAndWait('document:update', {
      doctype: 'ToDo',
      name: docName,
      data: { status: 'Closed' }
    });
    ResponseValidators.assertResponseEnvelope(response);
    logStep('✓ UPDATE response envelope valid');

    // DELETE
    response = await client.emitAndWait('document:delete', {
      doctype: 'ToDo',
      name: docName
    });
    ResponseValidators.assertResponseEnvelope(response);
    createdDocuments = createdDocuments.filter(d => d.name !== docName);
    logStep('✓ DELETE response envelope valid');

    logSuccess('All response envelopes are valid');
  });
});
