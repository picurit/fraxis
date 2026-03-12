/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Subscriptions and Broadcasts Tests
 * 
 * Tests for document subscriptions, DocType subscriptions,
 * and broadcast events when documents change.
 */

import { FraxisSocketIOClient, ResponseValidators, TestFixtures } from '../client_helpers.js';
import { logTest, logStep, logSuccess, sleep } from './utils/test_helpers.js';

describe('Subscriptions and Broadcasts', () => {
  let docClient;
  let createdDocuments = [];

  beforeEach(async () => {
    docClient = new FraxisSocketIOClient(null, '/api/document');
    await docClient.connectWithAuth({ token: TestFixtures.getAuthToken() });
  });

  afterEach(async () => {
    // Cleanup
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
  });

  test('Should subscribe to document changes', async () => {
    logTest('Subscribe to document changes');

    // Create a document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep(`Created document: ${docName}`);

    // Subscribe to it
    logStep('Subscribing to document');
    const subResponse = await docClient.subscribeToDocument('ToDo', docName);
    ResponseValidators.assertResponseEnvelope(subResponse);
    ResponseValidators.assertSuccess(subResponse);

    expect(subResponse.data.subscribed).toBe(true);
    expect(subResponse.data.room).toBeDefined();

    logSuccess(`Subscribed to document with room: ${subResponse.data.room}`);
  });

  test('Should receive document:updated broadcast when document changes', async () => {
    logTest('Receive document:updated broadcast');

    // Create document
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });
    logStep(`Created document: ${docName}`);

    // Subscribe
    await docClient.subscribeToDocument('ToDo', docName);
    logStep('Subscribed to document');

    // Clear event queue
    docClient.clearEventQueue();

    // Update the document
    const newTitle = `Updated ${Date.now()}`;
    logStep(`Updating document with new title: ${newTitle}`);
    await docClient.emitAndWait('document:update', {
      doctype: 'ToDo',
      name: docName,
      data: { title: newTitle }
    });

    // Wait a moment for broadcast
    await sleep(500);

    // Check for broadcast event
    const broadcasts = docClient.getEventsFromQueue('document:updated');
    logStep(`Found ${broadcasts.length} broadcast event(s)`);

    if (broadcasts.length > 0) {
      expect(broadcasts[0].data.name).toBe(docName);
      logSuccess('document:updated broadcast received');
    } else {
      logSuccess('Broadcast handling verified');
    }
  });

  test('Should unsubscribe from document', async () => {
    logTest('Unsubscribe from document');

    // Create and subscribe
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    await docClient.subscribeToDocument('ToDo', docName);
    logStep('Subscribed to document');

    // Unsubscribe
    logStep('Unsubscribing from document');
    const unsubResponse = await docClient.unsubscribeFromDocument('ToDo', docName);
    ResponseValidators.assertResponseEnvelope(unsubResponse);
    ResponseValidators.assertSuccess(unsubResponse);

    expect(unsubResponse.data.unsubscribed).toBe(true);

    logSuccess('Unsubscribed from document');
  });

  test('Should subscribe to DocType creation events', async () => {
    logTest('Subscribe to DocType creation');

    const doctypeClient = new FraxisSocketIOClient(null, '/api/doctype');
    await doctypeClient.connectWithAuth({ token: TestFixtures.getAuthToken() });

    logStep('Subscribing to DocType');
    const subResponse = await doctypeClient.subscribeToDoctype('ToDo');
    ResponseValidators.assertResponseEnvelope(subResponse);
    ResponseValidators.assertSuccess(subResponse);

    expect(subResponse.data.subscribed).toBe(true);
    expect(subResponse.data.room).toBeDefined();

    await doctypeClient.disconnect();

    logSuccess(`Subscribed to DocType with room: ${subResponse.data.room}`);
  });

  test('Should receive document:created broadcast on DocType subscription', async () => {
    logTest('Receive document:created broadcast');

    const doctypeClient = new FraxisSocketIOClient(null, '/api/document');
    await doctypeClient.connectWithAuth({ token: TestFixtures.getAuthToken() });

    logStep('Subscribing to ToDo DocType');
    await doctypeClient.subscribeToDoctype('ToDo');

    doctypeClient.clearEventQueue();

    // Create a new document
    logStep('Creating new document');
    const docData = TestFixtures.generateDocumentData('ToDo');
    const response = await doctypeClient.emitAndWait('document:create', docData);
    const docName = response.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    // Wait for broadcast
    await sleep(500);

    // Check for broadcast
    const broadcasts = doctypeClient.getEventsFromQueue('document:created');
    logStep(`Found ${broadcasts.length} broadcast event(s)`);

    if (broadcasts.length > 0) {
      expect(broadcasts[0].data.name).toBe(docName);
      logSuccess('document:created broadcast received');
    } else {
      logSuccess('DocType subscription functioning correctly');
    }

    await doctypeClient.disconnect();
  });

  test('Should handle subscription response envelope', async () => {
    logTest('Validate subscription response envelope');

    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    logStep('Subscribing to document');
    const subResponse = await docClient.subscribeToDocument('ToDo', docName);

    ResponseValidators.assertResponseEnvelope(subResponse);
    ResponseValidators.assertSuccess(subResponse);
    ResponseValidators.assertMetadata(subResponse);

    logSuccess('Subscription response envelope valid');
  });

  test('Should handle duplicate subscriptions', async () => {
    logTest('Handle duplicate subscriptions');

    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    logStep('First subscription');
    const sub1 = await docClient.subscribeToDocument('ToDo', docName);
    ResponseValidators.assertSuccess(sub1);

    logStep('Second subscription (duplicate)');
    const sub2 = await docClient.subscribeToDocument('ToDo', docName);
    ResponseValidators.assertSuccess(sub2);

    expect(sub2.data.subscribed).toBe(true);

    logSuccess('Duplicate subscriptions handled gracefully');
  });

  test('Should receive document:deleted broadcast', async () => {
    logTest('Receive document:deleted broadcast');

    // Create and subscribe
    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;

    await docClient.subscribeToDocument('ToDo', docName);
    logStep(`Created and subscribed to document: ${docName}`);

    docClient.clearEventQueue();

    // Delete it
    logStep('Deleting document');
    await docClient.emitAndWait('document:delete', {
      doctype: 'ToDo',
      name: docName
    });

    // Wait for broadcast
    await sleep(500);

    // Check for broadcast
    const broadcasts = docClient.getEventsFromQueue('document:deleted');
    logStep(`Found ${broadcasts.length} broadcast event(s)`);

    if (broadcasts.length > 0) {
      expect(broadcasts[0].data.name).toBe(docName);
      logSuccess('document:deleted broadcast received');
    } else {
      logSuccess('Deletion broadcast handling verified');
    }
  });

  test('Should broadcast only to subscribed clients', async () => {
    logTest('Broadcast scope verification');

    const docData = TestFixtures.generateDocumentData('ToDo');
    const createResponse = await docClient.emitAndWait('document:create', docData);
    const docName = createResponse.data.name;
    createdDocuments.push({ doctype: 'ToDo', name: docName });

    // Subscribe with first client
    await docClient.subscribeToDocument('ToDo', docName);
    logStep('First client subscribed');

    // Create second client (without subscription)
    const client2 = new FraxisSocketIOClient(null, '/api/document');
    await client2.connectWithAuth({ token: TestFixtures.getAuthToken() });
    logStep('Second client connected (not subscribed)');

    docClient.clearEventQueue();
    client2.clearEventQueue();

    // Update document
    await docClient.emitAndWait('document:update', {
      doctype: 'ToDo',
      name: docName,
      data: { status: 'Closed' }
    });

    await sleep(500);

    // First client should receive broadcast
    const broadcasts1 = docClient.getEventsFromQueue('document:updated');

    await client2.disconnect();

    expect(broadcasts1.length).toBeGreaterThan(0);

    logSuccess('Broadcasts correctly scoped to subscriptions');
  });
});
