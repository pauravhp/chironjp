import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildA16zListUrl,
  fetchA16zSpeedrunList,
  normalizeA16zListJob,
  scanA16zSpeedrun,
} from '../../src/sourcing/a16z-speedrun-talent.mjs';

function rawJob(id, overrides = {}) {
  return {
    id,
    title: 'Backend Engineer',
    company: 'Example Co',
    url: `https://speedrun-talent-network.com/jobs/backend-example-${id}?utm_source=chironjp`,
    location: 'Berlin',
    remote: false,
    published_at: '2026-09-10',
    ...overrides,
  };
}

test('builds the official 0-based list URL with provider filters and attribution', () => {
  const url = new URL(buildA16zListUrl({
    q: 'machine learning',
    functions: ['engineering', 'research'],
    seniority: ['senior'],
    locations: ['remote'],
    remote: true,
    minCompensation: 150000,
    scope: 'portfolio',
    sort: 'new',
  }, 3));
  assert.equal(url.origin + url.pathname, 'https://speedrun-talent-network.com/api/v1/jobs');
  assert.equal(url.searchParams.get('page'), '3');
  assert.equal(url.searchParams.get('source'), 'chironjp');
  assert.equal(url.searchParams.get('q'), 'machine learning');
  assert.equal(url.searchParams.get('fn'), 'engineering,research');
  assert.equal(url.searchParams.get('sen'), 'senior');
  assert.equal(url.searchParams.get('loc'), 'remote');
  assert.equal(url.searchParams.get('remote'), '1');
  assert.equal(url.searchParams.get('comp'), '150000');
  assert.equal(url.searchParams.get('scope'), 'portfolio');
  assert.equal(url.searchParams.get('sort'), 'new');
});

test('normalizes list records and rejects unsafe or incomplete records', () => {
  assert.deepEqual(normalizeA16zListJob(rawJob('a', { remote: true })), {
    source: 'a16z-speedrun-talent',
    sourceJobId: 'a',
    sourceUrl: 'https://speedrun-talent-network.com/jobs/backend-example-a',
    company: 'Example Co',
    title: 'Backend Engineer',
    location: 'Berlin, Remote',
    postedAt: '2026-09-10T00:00:00.000Z',
  });
  assert.equal(normalizeA16zListJob(rawJob('b', { url: 'https://evil.example/jobs/b' })), null);
  assert.equal(normalizeA16zListJob(rawJob('', {})), null);
});

test('paginates through a short rotating page when total_pages says more', async () => {
  const calls = [];
  const fetchJsonWithRetry = async (url) => {
    const page = Number(new URL(url).searchParams.get('page'));
    calls.push(page);
    const count = page === 1 ? 49 : 50;
    return {
      jobs: Array.from({ length: count }, (_, index) => rawJob(`${page}-${index}`)),
      total_pages: 3,
    };
  };
  const jobs = await fetchA16zSpeedrunList({ maxPages: 5 }, { fetchJsonWithRetry });
  assert.deepEqual(calls, [0, 1, 2]);
  assert.equal(jobs.length, 149);
});

test('an empty page terminates an over-reported feed', async () => {
  const calls = [];
  const fetchJsonWithRetry = async (url) => {
    const page = Number(new URL(url).searchParams.get('page'));
    calls.push(page);
    return { jobs: page < 2 ? Array.from({ length: 50 }, (_, i) => rawJob(`${page}-${i}`)) : [], total_pages: 99 };
  };
  const jobs = await fetchA16zSpeedrunList({ maxPages: 10 }, { fetchJsonWithRetry });
  assert.deepEqual(calls, [0, 1, 2]);
  assert.equal(jobs.length, 100);
});

test('scan filters before detail enrichment, excludes closed jobs, and deduplicates by official apply identity', async () => {
  const detailCalls = [];
  const list = [
    rawJob('keep-1'),
    rawJob('keep-2', { company: 'Duplicate Syndication' }),
    rawJob('old', { published_at: '2025-01-01' }),
    rawJob('blocked', { title: 'Sales Engineer' }),
    rawJob('closed'),
  ];
  const fetchJsonWithRetry = async (url) => {
    const parsed = new URL(url);
    if (parsed.pathname === '/api/v1/jobs') return { jobs: list, total_pages: 1 };
    const id = parsed.pathname.split('/').at(-1);
    detailCalls.push(id);
    const original = list.find((job) => job.id === id);
    return {
      job: {
        ...original,
        url: original.url.split('?')[0],
        status: id === 'closed' ? 'closed' : 'open',
        apply: { kind: 'external', url: 'https://jobs.ashbyhq.com/Acme/role-42/application?utm_source=feed' },
        description_text: `Description for ${id}`,
      },
    };
  };

  const jobs = await scanA16zSpeedrun({
    maxPages: 1,
    titleFilter: { positive: ['engineer'], negative: ['sales'] },
    maxPostingAgeDays: 30,
    scrapedAt: '2026-09-15T12:00:00.000Z',
  }, { fetchJsonWithRetry });

  assert.deepEqual(detailCalls.sort(), ['closed', 'keep-1', 'keep-2']);
  assert.equal(jobs.length, 1);
  assert.deepEqual(jobs[0], {
    source: 'a16z-speedrun-talent',
    sourceJobId: 'keep-1',
    sourceUrl: 'https://speedrun-talent-network.com/jobs/backend-example-keep-1',
    applyUrl: 'https://jobs.ashbyhq.com/Acme/role-42/application',
    company: 'Example Co',
    title: 'Backend Engineer',
    location: 'Berlin',
    description: 'Description for keep-1',
    postedAt: '2026-09-10T00:00:00.000Z',
    scrapedAt: '2026-09-15T12:00:00.000Z',
    officialApplyIdentity: 'ashby:acme:role-42',
  });
});

test('list filter leaves missing locations and missing dates eligible', async () => {
  const fetchJsonWithRetry = async (url) => {
    const parsed = new URL(url);
    if (parsed.pathname === '/api/v1/jobs') {
      return { jobs: [rawJob('x', { location: null, published_at: null })], total_pages: 1 };
    }
    return {
      job: {
        ...rawJob('x', { location: null, published_at: null }),
        status: 'open',
        apply: { kind: 'onsite', url: 'https://speedrun-talent-network.com/jobs/backend-example-x' },
        description_text: null,
      },
    };
  };
  const jobs = await scanA16zSpeedrun({
    locationFilter: { allow: ['berlin'], block: [] },
    maxPostingAgeDays: 1,
    scrapedAt: '2026-09-15T12:00:00.000Z',
  }, { fetchJsonWithRetry });
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].location, '');
  assert.equal(jobs[0].postedAt, null);
});
