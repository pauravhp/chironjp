const DEFAULT_TIMEOUT_MS = 15_000;
const RETRY_DEFAULTS = Object.freeze({ retries: 2, baseDelayMs: 500, maxDelayMs: 8_000 });

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function isRetryableError(error) {
  if (error?.status === 429) return true;
  if (typeof error?.status === 'number') return error.status >= 500;
  if (error instanceof TypeError && error?.cause?.message === 'unexpected redirect') return false;
  return true;
}

export async function fetchJson(url, options = {}) {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchImpl = globalThis.fetch,
    headers = {},
    ...fetchOptions
  } = options;
  if (typeof fetchImpl !== 'function') throw new Error('No Fetch API implementation is available');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, {
      ...fetchOptions,
      redirect: 'error',
      headers: {
        accept: 'application/json',
        'user-agent': 'chironjp/0.1 (+https://github.com/pauravhp/chironjp)',
        ...headers,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`);
      error.status = response.status;
      error.retryAfter = response.headers.get('retry-after');
      throw error;
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function retryAfterMs(value, now = Date.now()) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, timestamp - now) : null;
}

export async function fetchJsonWithRetry(url, options = {}, dependencies = {}) {
  const policy = { ...RETRY_DEFAULTS, ...(dependencies.retryPolicy ?? {}) };
  const request = dependencies.fetchJson ?? fetchJson;
  const wait = dependencies.sleep ?? sleep;
  let lastError;

  for (let attempt = 0; attempt <= policy.retries; attempt += 1) {
    try {
      return await request(url, options);
    } catch (error) {
      lastError = error;
      if (attempt === policy.retries || !isRetryableError(error)) throw error;
      const jitterRoom = Math.min(250, Math.max(0, policy.maxDelayMs));
      const backoff = Math.min(policy.baseDelayMs * (2 ** attempt), Math.max(0, policy.maxDelayMs - jitterRoom));
      const requestedDelay = retryAfterMs(error?.retryAfter);
      const delay = requestedDelay === null
        ? backoff + Math.random() * jitterRoom
        : Math.min(requestedDelay, policy.maxDelayMs * 4);
      await wait(delay);
    }
  }
  throw lastError;
}
