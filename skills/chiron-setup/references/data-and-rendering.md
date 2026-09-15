# Canonical profile, bank, and Tailor contract

Use the actual public Chiron structures. Do not create a parallel profile, resume bank, or Markdown renderer.

## Canonical profile answers

`config/canonical-profile-overrides.json` keeps identity, ATS name mapping, contact, location, citizenship/residence, education, professional-employer history, work authorization, application preferences, employment declarations, owner-authored narrative material, demographics, and canonical answers distinct. Its public template uses empty strings or nulls for personal answers.

Current work authorization and future employer sponsorship are separate, jurisdiction-specific values. Location, relocation, availability/start date, compensation, referral/source, and education also remain separate. Race/ethnicity, gender, disability, veteran, and other demographic categories must not be collapsed; the owner may choose any offered decline-to-answer option.

The agent may map exact employer wording to a typed canonical category and fill values the owner already supplied or authorized, including name/signature and demographic preferences. It must not infer a sensitive answer or convert silence into consent. Human action is required when the rendered site itself requires human authentication, CAPTCHA, or consent. Employer wording and jurisdictional meaning vary, so store the exact question with private application state, not in this public repository.

## Resume bank

`resume/bank.json` uses `schema_version: 1` and these established fields:

- `canonical_summary`: `body`, `default_label`, and offered `labels`;
- `experience`: fixed-order entries with stable IDs, employer/title/dates/location, bullet floors/targets, and canonical tagged bullets;
- `projects`: stable IDs, technologies, dates, tags, approved text/bullets and links, plus optional approved variants;
- `leadership` and `awards`, including the `required` flag on mandatory awards;
- grouped `canonical_skills`, `skill_evidence` with optional aliases, `skill_exclusions`, and `skill_sources` provenance.

Owner-confirmed facts learned in interviews are normalized into `skill_sources`/`skill_evidence` and, only when appropriate, canonical bullets. This is the canonical interview-evidence path; do not invent a second interview-bank schema. Never copy private example values into a public or new user's bank.

## Tailor selection

A selection manifest contains `schema_version`, one offered `summary_label`, exact `experience_order`, an experience-to-bullet-ID map, exactly two distinct project IDs, any required `project_variants`, leadership bullet IDs, all required award IDs, one to four nonempty skill categories using known inventory/aliases only, and `jd_coverage` objects:

```json
{"term":"named technology","jd_quote":"exact employer text","skill":null,"reason":"owner confirmation required"}
```

Map a term to a canonical skill only when evidence supports it. Unknown or excluded skills never become resume claims. A Tailor may select IDs and categories; it may not invent prose.

## Render and accept

Use the repository's `chironjp.resume` API and the value-free `resume/template.tex`, passing the canonical profile explicitly with `profile_path`/`--profile`. Rendering fills identity/contact/education from that profile, binds the profile, bank, template, manifest, role, and job description by hash, and compiles LaTeX reproducibly. Runtime binaries resolve from `CHIRONJP_TECTONIC`, `CHIRONJP_PDFTOTEXT`, and `CHIRONJP_PDFTOPPM`, then `PATH`; do not bake machine paths into config.

The public fictional path exercises the real contract without a live provider:

```bash
chironjp-resume check \
  --profile examples/fictional/canonical-profile-overrides.json \
  --bank examples/fictional/resume-bank.actual.json \
  --template resume/template.tex \
  --role 'Backend Engineer' \
  --description 'Build reliable services with Python and PostgreSQL.' \
  --manifest examples/fictional/resume-manifest.actual.json

chironjp-resume render \
  --profile examples/fictional/canonical-profile-overrides.json \
  --bank examples/fictional/resume-bank.actual.json \
  --template resume/template.tex \
  --role 'Backend Engineer' \
  --description 'Build reliable services with Python and PostgreSQL.' \
  --manifest examples/fictional/resume-manifest.actual.json \
  --output-dir ./private-runtime/resume
```

Deterministic PASS requires exactly one page, four readable rendered Skills lines, no TeX overflow, no clipped text, no text intersections, and a generated PNG preview. Then inspect the **exact PNG** with vision at readable scale. Bind the result to the returned selection hash, preview hash, and exact preview path:

```json
{
  "schema_version": 1,
  "selection_sha256": "<validation selection_sha256>",
  "preview_sha256": "<validation preview_sha256>",
  "passed": true,
  "inspected_preview_path": "<validation preview_path>",
  "obvious_defects": [],
  "notes": "Readable whole-page visual inspection"
}
```

Any content, geometry, or visual failure requires a materially changed selection and a new exact preview. Tests can prove validation behavior; they are not evidence that a human or vision model inspected a production resume.
