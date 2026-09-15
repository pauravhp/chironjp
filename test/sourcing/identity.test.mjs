import assert from 'node:assert/strict';
import test from 'node:test';

import { canonicalizeApplyIdentity, normalizeWebUrl } from '../../src/sourcing/identity.mjs';

test('normalizes tracking parameters and fragments without discarding functional query parameters', () => {
  assert.equal(
    normalizeWebUrl('https://www.example.com/jobs/42/?utm_source=feed&candidate=abc#apply'),
    'https://example.com/jobs/42?candidate=abc',
  );
});

test('collapses common official ATS page and application URL variants', () => {
  assert.equal(
    canonicalizeApplyIdentity('https://job-boards.greenhouse.io/Acme/jobs/123?gh_src=abc'),
    'greenhouse:acme:123',
  );
  assert.equal(
    canonicalizeApplyIdentity('https://jobs.ashbyhq.com/Acme/ABC-123/application?utm_medium=feed'),
    'ashby:acme:abc-123',
  );
  assert.equal(
    canonicalizeApplyIdentity('https://apply.lever.co/Acme/ABC-123/apply?lever-source=feed'),
    'lever:acme:abc-123',
  );
});

test('uses a normalized full URL for unknown official application hosts', () => {
  assert.equal(
    canonicalizeApplyIdentity('https://careers.example/jobs/7/?utm_campaign=x&lang=en'),
    'url:https://careers.example/jobs/7?lang=en',
  );
  assert.equal(canonicalizeApplyIdentity('mailto:jobs@example.com'), null);
  assert.equal(canonicalizeApplyIdentity('https://careers.example/jobs/100%/apply'), 'url:https://careers.example/jobs/100%/apply');
});
