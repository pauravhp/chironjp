# Canonical resume composition

ChironJP includes a sanitized extraction of Chiron's actual manifest-driven
Python/LaTeX resume boundary. An agent may inspect the finite canonical bank and
choose IDs, but it cannot write new resume claims through this API. The renderer
copies the selected canonical text verbatim, escapes it for LaTeX, compiles a
PDF, checks the rendered geometry, and creates an exact PNG for a separate
visual inspection.

The included candidate, organizations, projects, history, and award are wholly
fictional. They demonstrate the contract and are not application or delivery
evidence.

## Files and ownership

- `resume/bank.template.json` is the blank schema. Keep the completed bank
  private when it contains real candidate facts.
- `resume/template.tex` is value-free. Identity, contact, and education are
  populated from the canonical profile at render time.
- `examples/fictional/resume-bank.actual.json` is a runnable, actual-schema bank.
- `examples/fictional/resume-manifest.actual.json` is an explicit selection for
  the fictional job description used below.
- `examples/fictional/canonical-profile-overrides.json` supplies the runnable
  fictional identity and education rows.

Canonical content is immutable at composition time. Normalize facts from
resumes and owner interviews into the bank first, keep their source keys in
`skill_sources`, and point `skill_evidence` or `skill_exclusions` at those keys.
Do not treat a job description as evidence that the candidate has a skill.
Each education row owns its explicit `location`. A current row renders
`expected_end`; a completed row renders `completed_end`. Missing geography or
end dates remain blank and are never inferred from the candidate's address.

## Contract

The bank uses `schema_version: 1` and contains:

- a fixed summary body plus a finite set of labels;
- ordered experience entries with canonical bullet IDs and minimum counts;
- a project bank, optionally with explicit `variants` and a `default_variant`;
- leadership bullets and required or optional awards;
- grouped canonical skills, evidence sources, aliases, and explicit exclusions.

The manifest chooses one summary label, preserves the exact experience order,
selects canonical bullet IDs, selects exactly two distinct projects, chooses a
variant for every selected variant-bearing project, includes every required
award, and provides one to four role-specific skill groups drawn only from the
known inventory. `jd_coverage` records each technology or concept found by a
whole-description analysis with its exact description quote, canonical skill or
`null`, and the mapping reason. Deterministic hints catch obvious omissions;
they are not a semantic selector or a fallback.

The intended final layout has exactly four readable rendered Skills lines.
Because wrapping is a property of the PDF, this is enforced after compilation.

## Validate and render the fictional example

Install the package in a virtual environment, then make Tectonic and Poppler's
`pdftotext` and `pdftoppm` available on `PATH`. Each tool can instead be set by
an absolute executable path in `CHIRONJP_TECTONIC`, `CHIRONJP_PDFTOTEXT`, or
`CHIRONJP_PDFTOPPM`.

```bash
python3 -m pip install -e '.[test]'

chironjp-resume check \
  --bank examples/fictional/resume-bank.actual.json \
  --template resume/template.tex \
  --profile examples/fictional/canonical-profile-overrides.json \
  --role 'Backend Engineer' \
  --description 'Build reliable services with Python and PostgreSQL.' \
  --manifest examples/fictional/resume-manifest.actual.json

chironjp-resume render \
  --bank examples/fictional/resume-bank.actual.json \
  --template resume/template.tex \
  --profile examples/fictional/canonical-profile-overrides.json \
  --role 'Backend Engineer' \
  --description 'Build reliable services with Python and PostgreSQL.' \
  --manifest examples/fictional/resume-manifest.actual.json \
  --output-dir ./private-runtime/resume
```

The Python entry points are:

```python
from chironjp.resume import render_agent_manifest, tailor_contract, validate_manifest
```

`tailor_contract` exposes the finite bank and SHA-256 bindings.
`validate_manifest` validates an in-memory manifest and composes TeX without
executing external tools. `render_agent_manifest` accepts a manifest path and an
explicit output directory, writes artifacts beneath a content-addressed
`renders/<id>/` directory, and returns a validation report.

## Automated checks and vision contract

A renderer PASS requires all of the following:

- successful Tectonic compilation with no overfull horizontal or vertical box;
- exactly one PDF page with extractable text;
- exactly four rendered Skills lines;
- no word box outside the page bounds;
- zero rendered text-intersection regions;
- an exact 180 DPI single-page PNG from `pdftoppm`.

The report binds the input manifest, normalized selection, bank, template,
renderer, TeX source, PDF, PNG, and compiler evidence with SHA-256 hashes.
Automated geometry is necessary but not sufficient. A human or vision-capable
agent must inspect the exact `preview_path` returned by the report and record
`schema_version`, `passed`, `obvious_defects`, `selection_sha256`,
`preview_sha256`, and `inspected_preview_path`. If content or visual inspection
fails, change the manifest selection and render again; never silently invoke a
legacy semantic selector.

This stage prepares an artifact for Review only. It does not submit, send, or
confirm anything on an employer site.
