import { fetchJsonWithRetry } from './http.mjs';
import { canonicalizeApplyIdentity, normalizeWebUrl } from './identity.mjs';
import { buildJobFilter } from './filters.mjs';

export const A16Z_SPEEDRUN_SOURCE = 'a16z-speedrun-talent';
export const A16Z_SPEEDRUN_FEED = 'https://speedrun-talent-network.com/api/v1/jobs';

const TRUSTED_HOST = 'speedrun-talent-network.com';
const PAGE_SIZE = 50;
const DEFAULT_MAX_PAGES = 6;
const MAX_PAGES_CAP = 1_000;
const API_SOURCE_TAG = 'chironjp';

function trustedSourceUrl(rawUrl) {
  const value = normalizeWebUrl(rawUrl);
  if (!value) return null;
  const url = new URL(value);
  return url.protocol === 'https:' && url.hostname === TRUSTED_HOST ? value : null;
}

function isoDate(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
}

function locationFor(job) {
  const location = typeof job?.location === 'string' ? job.location.trim() : '';
  if (job?.remote !== true || /\bremote\b/i.test(location)) return location;
  return [location, 'Remote'].filter(Boolean).join(', ');
}

export function normalizeA16zListJob(job) {
  if (!job || typeof job !== 'object') return null;
  const sourceJobId = typeof job.id === 'string' ? job.id.trim() : '';
  const title = typeof job.title === 'string' ? job.title.trim() : '';
  const company = typeof job.company === 'string' ? job.company.trim() : '';
  const sourceUrl = trustedSourceUrl(job.url);
  if (!sourceJobId || !title || !company || !sourceUrl) return null;
  return {
    source: A16Z_SPEEDRUN_SOURCE,
    sourceJobId,
    sourceUrl,
    company,
    title,
    location: locationFor(job),
    postedAt: isoDate(job.published_at),
  };
}

export function normalizeA16zDetail(payload, listJob, scrapedAt) {
  const detail = payload?.job;
  if (!detail || detail.status !== 'open') return null;
  const normalized = normalizeA16zListJob(detail);
  if (!normalized || normalized.sourceJobId !== listJob.sourceJobId) return null;
  const applyUrl = normalizeWebUrl(detail.apply?.url);
  const description = typeof detail.description_text === 'string' && detail.description_text.trim()
    ? detail.description_text.trim()
    : null;
  return {
    ...normalized,
    applyUrl,
    description,
    postedAt: normalized.postedAt ?? listJob.postedAt,
    scrapedAt,
    officialApplyIdentity: canonicalizeApplyIdentity(applyUrl),
  };
}

function positiveInteger(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function setCsv(params, key, value) {
  const values = Array.isArray(value) ? value : [];
  const clean = values.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim());
  if (clean.length > 0) params.set(key, clean.join(','));
}

export function buildA16zListUrl(options = {}, page = 0) {
  const params = new URLSearchParams({ page: String(page), source: API_SOURCE_TAG });
  const query = typeof options.q === 'string' && options.q.trim()
    ? options.q.trim()
    : Array.isArray(options.keywords)
      ? options.keywords.filter((word) => typeof word === 'string' && word.trim()).join(' ').trim()
      : '';
  if (query) params.set('q', query);
  setCsv(params, 'fn', options.functions);
  setCsv(params, 'sen', options.seniority);
  setCsv(params, 'emp', options.employmentTypes);
  setCsv(params, 'loc', options.locations);
  setCsv(params, 'portfolio', options.portfolio);
  setCsv(params, 'cohort', options.cohorts);
  if (options.remote === true) params.set('remote', '1');
  if (Number.isFinite(options.minCompensation) && options.minCompensation >= 0) params.set('comp', String(options.minCompensation));
  for (const [option, key] of [['company', 'company'], ['stealth', 'stealth'], ['scope', 'scope'], ['sort', 'sort']]) {
    if (typeof options[option] === 'string' && options[option].trim()) params.set(key, options[option].trim());
  }
  return `${A16Z_SPEEDRUN_FEED}?${params}`;
}

export async function fetchA16zSpeedrunList(options = {}, dependencies = {}) {
  const request = dependencies.fetchJsonWithRetry ?? fetchJsonWithRetry;
  const maxPages = Math.min(positiveInteger(options.maxPages, DEFAULT_MAX_PAGES), MAX_PAGES_CAP);
  const output = [];

  for (let page = 0; page < maxPages; page += 1) {
    const payload = await request(buildA16zListUrl(options, page), { timeoutMs: options.timeoutMs }, dependencies);
    if (!payload || !Array.isArray(payload.jobs)) {
      throw new Error(`${A16Z_SPEEDRUN_SOURCE}: unexpected list response on page ${page}; expected { jobs: [...] }`);
    }
    for (const rawJob of payload.jobs) {
      const job = normalizeA16zListJob(rawJob);
      if (job) output.push(job);
    }

    if (payload.jobs.length === 0) break;
    if (Number.isInteger(payload.total_pages) && payload.total_pages > 0) {
      if (page + 1 >= payload.total_pages) break;
    } else if (payload.jobs.length < PAGE_SIZE) {
      break;
    }
    if (page + 1 >= maxPages && Number.isInteger(payload.total_pages) && payload.total_pages > maxPages) {
      dependencies.onWarning?.(`${A16Z_SPEEDRUN_SOURCE}: truncated at maxPages=${maxPages}; narrow filters or raise the page budget`);
    }
  }
  return output;
}

async function mapConcurrent(values, limit, fn) {
  const output = new Array(values.length);
  let next = 0;
  async function worker() {
    while (next < values.length) {
      const index = next;
      next += 1;
      output[index] = await fn(values[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, () => worker()));
  return output;
}

function deduplicate(jobs) {
  const identities = new Set();
  const sourceIds = new Set();
  return jobs.filter((job) => {
    if (!job) return false;
    const identity = job.officialApplyIdentity;
    if (sourceIds.has(job.sourceJobId) || (identity && identities.has(identity))) return false;
    sourceIds.add(job.sourceJobId);
    if (identity) identities.add(identity);
    return true;
  });
}

/**
 * Fetch, filter, detail-enrich, and official-apply-deduplicate the featured
 * public provider. This function performs no persistence.
 */
export async function scanA16zSpeedrun(options = {}, dependencies = {}) {
  const request = dependencies.fetchJsonWithRetry ?? fetchJsonWithRetry;
  const scrapedAt = options.scrapedAt ?? new Date(dependencies.now?.() ?? Date.now()).toISOString();
  const filter = buildJobFilter({ ...options, now: Date.parse(scrapedAt) });
  const listJobs = (await fetchA16zSpeedrunList(options, dependencies)).filter(filter);
  const concurrency = Math.min(positiveInteger(options.detailConcurrency, 4), 16);
  const details = await mapConcurrent(listJobs, concurrency, async (listJob) => {
    const id = encodeURIComponent(listJob.sourceJobId);
    const url = `${A16Z_SPEEDRUN_FEED}/${id}?source=${API_SOURCE_TAG}`;
    const payload = await request(url, { timeoutMs: options.timeoutMs }, dependencies);
    return normalizeA16zDetail(payload, listJob, scrapedAt);
  });
  return deduplicate(details);
}
