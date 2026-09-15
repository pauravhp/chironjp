# Public sourcing ingress

ChironJP currently ships one honest, runnable source: the public a16z speedrun
talent network feed. The ingress is read-only. It prints normalized NDJSON and
does not create application records, score roles, tailor résumés, or make
submission decisions.

## Run it

Node.js 20 or newer is required. No API key is needed.

```sh
npm install
npm run scan -- --query "backend engineer" --max-pages 2
```

Each stdout line is a JSON object with this contract:

```json
{
  "source": "a16z-speedrun-talent",
  "sourceJobId": "provider UUID",
  "sourceUrl": "https://speedrun-talent-network.com/jobs/...",
  "applyUrl": "https://the-official-application-destination.example/...",
  "company": "Example Co",
  "title": "Backend Engineer",
  "location": "Berlin, Remote",
  "description": "Plain-text description or null",
  "postedAt": "2026-09-10T00:00:00.000Z",
  "scrapedAt": "2026-09-15T12:00:00.000Z",
  "officialApplyIdentity": "url:https://the-official-application-destination.example/..."
}
```

`applyUrl`, `description`, and `officialApplyIdentity` can be `null` when the
official detail response omits an application destination or description.
Closed details are not emitted. `postedAt` can be `null` when the provider has
no usable date.

The library entry point is `src/sourcing/index.mjs`. Integrators can call:

```js
import { scanA16zSpeedrun } from 'chironjp/sourcing';

const jobs = await scanA16zSpeedrun({
  q: 'backend engineer',
  maxPages: 2,
  titleFilter: { positive: ['engineer'], negative: ['sales'] },
  locationFilter: { allow: ['remote', 'berlin'], block: [] },
  maxPostingAgeDays: 30,
});
```

Title and location filters use case-insensitive substring matching. A missing
location or posting date passes its respective optional filter because absence
of provider data is not evidence of ineligibility. The official feed also
supports server-side `functions`, `seniority`, `employmentTypes`, `locations`,
`remote`, `minCompensation`, `portfolio`, `cohorts`, `company`, `stealth`,
`scope`, and `sort` options through the exported API.

## Pagination and identity

Pages are zero-based and contain 50 rows. The default budget is six pages (300
rows). An empty page always stops the scan. A positive `total_pages` value is
the authoritative terminator even if a rotating board returns a short page;
only feeds without that metadata stop on a short page. A warning is emitted
when the caller's page budget truncates a feed.

After list-level filtering, ChironJP requests each official detail endpoint to
obtain the plain-text description and official apply destination. Results are
deduplicated on that destination. Greenhouse, Ashby, and Lever job/application
URL variants collapse to an ATS-specific identity; other destinations use a
normalized URL with fragments and known tracking parameters removed.

## Generic VPS operation

Use any unprivileged service account and a current Node.js runtime. Configuration
is supplied through command-line flags; no fixed filesystem location, host,
port, domain, or secret is assumed. Capture stdout as NDJSON and keep stderr for
warnings. Schedule conservatively and use narrow queries or page budgets to
avoid unnecessary traffic to the public service.

## Current limits

- Only the `a16z-speedrun-talent` provider is included.
- Detail enrichment adds one request per list candidate that passes filters.
- The ingress does not verify arbitrary external apply pages and never submits.
- The upstream feed, its taxonomy, and availability are controlled by its owner.
- No scoring, personal preference defaults, résumé handling, or application
  persistence is part of this module.

## Upstream provenance

The pagination, normalization, bounded retry, and filtering behavior was adapted
from the MIT-licensed `career-ops` project at commit
`5296dcd18cdb9453225b43295f453846fee71bb2`, specifically `scan.mjs`,
`modes/scan.md`, `providers/_http.mjs`,
`providers/a16z-speedrun-talent.mjs`, and their focused tests. Attribution and
the upstream MIT notice are retained in `THIRD_PARTY_NOTICES.md`.
