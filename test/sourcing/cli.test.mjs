import assert from 'node:assert/strict';
import test from 'node:test';

import { parseArgs } from '../../bin/chironjp-sourcing.mjs';

test('CLI parses repeatable filters and bounded numeric options', () => {
  assert.deepEqual(parseArgs([
    '--keyword', 'machine', '--keyword', 'learning', '--positive', 'engineer',
    '--negative', 'sales', '--allow-location', 'remote', '--max-pages', '2',
    '--detail-concurrency', '3', '--remote',
  ]), {
    keywords: ['machine', 'learning'],
    titleFilter: { positive: ['engineer'], negative: ['sales'] },
    locationFilter: { allow: ['remote'], block: [] },
    maxPages: 2,
    detailConcurrency: 3,
    remote: true,
  });
  assert.throws(() => parseArgs(['--max-pages', '0']), /positive integer/);
  assert.throws(() => parseArgs(['--unknown']), /requires a value|Unknown option/);
});
