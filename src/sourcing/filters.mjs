function cleanKeywords(values) {
  if (!Array.isArray(values)) return [];
  return values.filter((value) => typeof value === 'string' && value.trim()).map((value) => value.trim().toLowerCase());
}

export function buildJobFilter(options = {}) {
  const positive = cleanKeywords(options.titleFilter?.positive);
  const negative = cleanKeywords(options.titleFilter?.negative);
  const allowLocations = cleanKeywords(options.locationFilter?.allow);
  const blockLocations = cleanKeywords(options.locationFilter?.block);
  const maxAge = Number(options.maxPostingAgeDays);
  const oldestAllowed = Number.isFinite(maxAge) && maxAge > 0
    ? (options.now ?? Date.now()) - maxAge * 86_400_000
    : null;

  return (job) => {
    const title = String(job.title ?? '').toLowerCase();
    if (positive.length > 0 && !positive.some((keyword) => title.includes(keyword))) return false;
    if (negative.some((keyword) => title.includes(keyword))) return false;

    const location = String(job.location ?? '').toLowerCase();
    if (location) {
      if (blockLocations.some((keyword) => location.includes(keyword))) return false;
      if (allowLocations.length > 0 && !allowLocations.some((keyword) => location.includes(keyword))) return false;
    }

    if (oldestAllowed !== null && job.postedAt) {
      const postedAt = Date.parse(job.postedAt);
      if (Number.isFinite(postedAt) && postedAt < oldestAllowed) return false;
    }
    return true;
  };
}
