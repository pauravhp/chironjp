const TRACKING_QUERY_KEYS = new Set([
  'fbclid',
  'gclid',
  'gh_src',
  'lever-source',
  'source',
  'src',
]);

function normalizedUrl(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
  url.hostname = url.hostname.toLowerCase().replace(/^www\./, '');
  url.hash = '';
  for (const key of [...url.searchParams.keys()]) {
    if (key.toLowerCase().startsWith('utm_') || TRACKING_QUERY_KEYS.has(key.toLowerCase())) {
      url.searchParams.delete(key);
    }
  }
  url.searchParams.sort();
  if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, '');
  return url;
}

/**
 * Derive an identity from the official application destination. Known ATS URL
 * shapes collapse their job page and application-form variants; other hosts
 * retain a normalized URL. Returns null when no web URL was supplied.
 */
export function canonicalizeApplyIdentity(applyUrl) {
  const url = normalizedUrl(applyUrl);
  if (!url) return null;
  const host = url.hostname;
  const parts = url.pathname.split('/').filter(Boolean).map((part) => {
    try {
      return decodeURIComponent(part);
    } catch {
      return part;
    }
  });

  if (host === 'boards.greenhouse.io' || host === 'job-boards.greenhouse.io') {
    const jobsIndex = parts.indexOf('jobs');
    if (jobsIndex > 0 && parts[jobsIndex + 1]) {
      return `greenhouse:${parts[jobsIndex - 1].toLowerCase()}:${parts[jobsIndex + 1].toLowerCase()}`;
    }
    if (parts[0] === 'embed' && parts[1] === 'job_app') {
      const board = url.searchParams.get('for');
      const token = url.searchParams.get('token');
      if (board && token) return `greenhouse:${board.toLowerCase()}:${token.toLowerCase()}`;
    }
  }

  if (host === 'jobs.ashbyhq.com' && parts.length >= 2) {
    return `ashby:${parts[0].toLowerCase()}:${parts[1].toLowerCase()}`;
  }

  if ((host === 'jobs.lever.co' || host === 'apply.lever.co') && parts.length >= 2) {
    return `lever:${parts[0].toLowerCase()}:${parts[1].toLowerCase()}`;
  }

  return `url:${url.href}`;
}

export function normalizeWebUrl(rawUrl) {
  return normalizedUrl(rawUrl)?.href ?? null;
}
