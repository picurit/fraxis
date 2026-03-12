/**
 * Copyright (c) 2026, Picurit and contributors
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
 * If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
 * For license information, please see license.txt
 */

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // Environment: Node.js (not browser/jsdom)
    environment: 'node',

    // Test file pattern - matches Jest's testMatch
    include: ['**/scenarios/**/*.test.js'],

    // Timeout: 30 seconds per test (real Socket.IO connections are slow)
    testTimeout: 30000,

    // Verbose output - show each test name as it runs
    reporters: ['verbose'],

    // Serial execution (replaces Jest's --runInBand)
    // Critical for Socket.IO integration tests that share server state
    fileParallelism: false,
    maxWorkers: 1,

    // Enable globals: describe, test, expect, beforeEach, afterEach
    // This allows zero changes to test file syntax
    globals: true,

    // Coverage configuration
    coverage: {
      provider: 'v8',  // Fast native coverage
      include: ['client_helpers.js'],
      exclude: ['node_modules/**'],
      reporter: ['text', 'json', 'html'],
    },
  },
})
