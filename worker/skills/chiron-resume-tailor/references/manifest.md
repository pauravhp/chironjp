# Tailor manifest contract

Write one JSON object with these fields:

- `schema_version`: `1`
- `summary_label`: one exact offered canonical label
- `experience_order`: the exact fixed order
- `experience_bullets`: experience IDs to ordered canonical bullet IDs
- `projects`: exactly two distinct canonical project IDs
- `project_variants`: any selected project ID with multiple variants to one
  exact offered variant ID
- `leadership_bullets`: one or two canonical IDs
- `awards`: every canonical award ID marked required
- `skills`: one to four concise role-specific labels to ordered, known skill
  strings
- `jd_coverage`: complete semantic job-description analysis as objects with
  `term`, an exact `jd_quote`, `skill`, and `reason`

Named technologies use their canonical identity or recorded aliases, not
adjacent substitutes. Concepts can map to an evidenced canonical skill when
the reason explains the relationship. Separate alternatives. Include all
deterministic hints and find relevant technical concepts beyond those hints;
hints are an omission check, not a vocabulary. An empty analysis is valid only
when the whole description contains no relevant technologies or technical
concepts.

For an unknown technology, use `skill: null` and explain that owner
confirmation is needed. For a recorded exclusion, use `skill: null`, cite that
boundary, and do not request confirmation. Never add a claim or silently omit
a named term.

The renderer normalizes the selection and binds it to the immutable role,
whole-description digest, profile, bank, template, and generated artifacts.
Its passing report includes exact paths and hashes for the normalized
selection and preview. After inspecting that exact preview, write:

```json
{
  "schema_version": 1,
  "selection_sha256": "<passing normalized selection hash>",
  "preview_sha256": "<passing PNG hash>",
  "passed": true,
  "inspected_preview_path": "<exact passing preview path>",
  "obvious_defects": [],
  "notes": "Concise actual visual readback"
}
```

Only the request's exact `finish_argv` may admit the artifact.
