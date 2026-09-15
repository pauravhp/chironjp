import assert from 'node:assert/strict';
import test from 'node:test';

import { fetchJsonWithRetry, isRetryableError } from '../../src/sourcing/http.mjs';

test('retries transient failures and fails fast on deterministic 4xx responses', async () => {
  let attempts = 0;
  const waits = [];
  const result = await fetchJsonWithRetry('https://example.test', {}, {
    fetchJson: async () => {
      attempts += 1;
      if (attempts < 3) {
        const error = new Error('unavailable');
        error.status = 503;
        throw error;
      }
      return { ok: true };
    },
    sleep: async (delay) => waits.push(delay),
  });
  assert.deepEqual(result, { ok: true });
  assert.equal(attempts, 3);
  assert.equal(waits.length, 2);

  attempts = 0;
  await assert.rejects(() => fetchJsonWithRetry('https://example.test', {}, {
    fetchJson: async () => {
      attempts += 1;
      const error = new Error('not found');
      error.status = 404;
      throw error;
    },
    sleep: async () => {},
  }), /not found/);
  assert.equal(attempts, 1);
});

test('a refused redirect is deterministic and is not retried', () => {
  const error = new TypeError('fetch failed', { cause: new Error('unexpected redirect') });
  assert.equal(isRetryableError(error), false);
});
