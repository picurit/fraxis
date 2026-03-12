/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

/**
 * Test Helper Functions
 * 
 * Common utilities used across all test suites
 */

/**
 * Sleep for a given duration
 */
export async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry a function with exponential backoff
 */
export async function retryWithBackoff(fn, maxRetries = 3, initialDelay = 100) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      const delay = initialDelay * Math.pow(2, i);
      await sleep(delay);
    }
  }
}

/**
 * Wait for a condition to be true
 */
export async function waitFor(condition, timeout = 5000, interval = 100) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    try {
      if (condition()) {
        return true;
      }
    } catch (error) {
      // Continue waiting
    }
    await sleep(interval);
  }
  throw new Error(`Condition not met within ${timeout}ms`);
}

/**
 * Generate a unique identifier
 */
export function generateId(prefix = 'test') {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Validate that a value is not undefined or null
 */
export function assertDefined(value, message) {
  if (value === undefined || value === null) {
    throw new Error(message || 'Value is undefined or null');
  }
}

/**
 * Validate that a value equals expected
 */
export function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(message || `Expected ${expected} but got ${actual}`);
  }
}

/**
 * Validate that a value is of expected type
 */
export function assertType(value, type, message) {
  if (typeof value !== type) {
    throw new Error(message || `Expected type ${type} but got ${typeof value}`);
  }
}

/**
 * Validate that a value is an array
 */
export function assertArray(value, message) {
  if (!Array.isArray(value)) {
    throw new Error(message || 'Expected an array');
  }
}

/**
 * Validate that a value is an object
 */
export function assertObject(value, message) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(message || 'Expected an object');
  }
}

/**
 * Validate that an object has a property
 */
export function assertHasProperty(object, property, message) {
  if (!(property in object)) {
    throw new Error(message || `Object missing property: ${property}`);
  }
}

/**
 * Validate that a value matches a condition
 */
export function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed: condition is not true');
  }
}

/**
 * Validate that a value does not match a condition
 */
export function assertFalse(condition, message) {
  if (condition) {
    throw new Error(message || 'Assertion failed: condition is true');
  }
}

/**
 * Log test progress
 */
export function logTest(message) {
  console.log(`\n[TEST] ${message}`);
}

/**
 * Log test step
 */
export function logStep(step) {
  console.log(`  → ${step}`);
}

/**
 * Log test success
 */
export function logSuccess(message) {
  console.log(`  ✓ ${message}`);
}

/**
 * Log test error
 */
export function logError(message) {
  console.error(`  ✗ ${message}`);
}
