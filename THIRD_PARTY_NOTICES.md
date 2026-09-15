# Third-party notices

## career-ops

Portions of the sourcing ingress are adapted from
[career-ops](https://github.com/career-ops-hq/career-ops) at the exact commit
[`5296dcd18cdb9453225b43295f453846fee71bb2`](https://github.com/career-ops-hq/career-ops/commit/5296dcd18cdb9453225b43295f453846fee71bb2).
The reviewed upstream files were `modes/scan.md`, `scan.mjs`,
`providers/_http.mjs`, `providers/_types.js`,
`providers/a16z-speedrun-talent.mjs`, and the related sourcing/provider tests.
The adapted ChironJP mapping is:

- upstream `providers/a16z-speedrun-talent.mjs` →
  `src/sourcing/a16z-speedrun-talent.mjs` (feed normalization and pagination);
- upstream `providers/_http.mjs` → `src/sourcing/http.mjs` (bounded retry and
  timeout behavior);
- upstream `scan.mjs` and `modes/scan.md` → `src/sourcing/filters.mjs` and
  `src/sourcing/a16z-speedrun-talent.mjs` (conservative optional filters and
  deduplication semantics);
- upstream focused provider/scanner tests → `test/sourcing/*.test.mjs`.

The upstream project is licensed under the MIT License:

> MIT License
>
> Copyright (c) 2026 Santiago Fernández de Valderrama
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

ChironJP changes include a smaller standalone module layout, an NDJSON boundary,
official-detail enrichment, official apply URL identities, and removal of the
upstream scoring, résumé, tracker, and personal-profile systems.

`career-ops` and ChironJP are independent projects. This notice describes
source provenance only; it does not imply sponsorship, endorsement, official
status, or affiliation. No upstream logo is used.

## yuyao-wang/Jobops

Workday mechanics in `chironjp/browser_tools.py` are adapted from
[`yuyao-wang/Jobops`](https://github.com/yuyao-wang/Jobops) at immutable commit
[`643f489936e07494941d58433da82826ed224ae8`](https://github.com/yuyao-wang/Jobops/commit/643f489936e07494941d58433da82826ed224ae8).
The reviewed upstream file was `adapters/workday.py`. Its stage markers,
compact field representation, exact-select/readback behavior, upload
verification, and guarded advancement inform the dependency-closed Workday
path in `chironjp/browser_tools.py`. ChironJP integrates those mechanics with
its own frame/CDP routing, canonical-answer boundary, retained Review guard,
and evidence contract.

The pinned upstream project is licensed under the MIT License:

> MIT License
>
> Copyright (c) 2025 humancto
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

`yuyao-wang/Jobops` and ChironJP are independent projects. This attribution
does not imply sponsorship, endorsement, official status, or affiliation.

## Browser Harness and browser-use runtime dependencies

The browser worker loads `agent_helpers.py` through
[`browser-use/browser-harness`](https://github.com/browser-use/browser-harness)
version `0.1.9`, release commit
[`41108b8676d4bdb58b26ab3b079c0b7b0f8f3926`](https://github.com/browser-use/browser-harness/commit/41108b8676d4bdb58b26ab3b079c0b7b0f8f3926).
The optional runtime also pins `browser-use==0.13.8`. These are dependencies,
not source copied into ChironJP. Browser Harness is MIT licensed:

> MIT License
>
> Copyright (c) 2026 Browser Use
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

`browser-use` is MIT licensed:

> MIT License
>
> Copyright (c) 2024 Gregor Zunic
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

These runtime dependencies and ChironJP are independent projects. Their names
and links identify required interoperability only and imply no sponsorship,
endorsement, official status, or affiliation.

## jakegut/resume and sb2nov/resume lineage

The public LaTeX template is adapted directly from
[`jakegut/resume`](https://github.com/jakegut/resume) at commit
[`3e64a933141a7cda3a328f0743f73a201628a4ba`](https://github.com/jakegut/resume/commit/3e64a933141a7cda3a328f0743f73a201628a4ba).
The adapted mapping is upstream `resume.tex` to `resume/template.tex`: the
preamble, page geometry, section formatting, and item, subheading, project, and
list macros. ChironJP parameterizes all candidate content, composes sections
from a canonical bank and explicit manifest, conditionally loads Unicode
support for Tectonic, and adds deterministic PDF validation. No upstream
personal content is included.

`jakegut/resume` is licensed under the MIT License:

> MIT License
>
> Copyright (c) 2020 Jake Gutierrez
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

The pinned Jake source identifies
[`sb2nov/resume`](https://github.com/sb2nov/resume) as its base. ChironJP records
that lineage at commit
[`7b70fe14876f97180034787f2a7f661597416a17`](https://github.com/sb2nov/resume/commit/7b70fe14876f97180034787f2a7f661597416a17).
That project is also MIT-licensed, with `Copyright (c) 2026 Sourabh Bajaj` in
the pinned license. ChironJP does not claim direct adaptation beyond the Jake
lineage described above. These provenance statements imply no sponsorship,
endorsement, official status, or affiliation.

## Cyrus workflow inspiration (no copied code)

The setup workflow was informed by the public Apache-2.0-licensed
[`cyrusagents/cyrus`](https://github.com/cyrusagents/cyrus) repository at exact
commit
[`035cfccc4856f2e853725779923e874d3af9cad8`](https://github.com/cyrusagents/cyrus/commit/035cfccc4856f2e853725779923e874d3af9cad8),
specifically its `README.md` and `skills/cyrus-setup/SKILL.md`.

No Cyrus source code or documentation text is included in ChironJP, so this is
voluntary provenance rather than a bundled-code license notice. The reviewed
upstream revision contains no `NOTICE` file. Cyrus and ChironJP are independent
projects; this provenance does not imply sponsorship, endorsement, official
status, or affiliation, and no Cyrus logo is used.
