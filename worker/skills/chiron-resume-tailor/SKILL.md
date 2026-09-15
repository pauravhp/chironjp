---
name: chiron-resume-tailor
description: Select and visually validate one immutable ChironJP resume from the request's canonical bank; use only in the non-browser Tailor profile.
---

# ChironJP resume Tailor

Work only on the single `tailor-brief.json` under
`$CHIRONJP_TAILOR_WORKSPACE`. Read the whole job description and the
[manifest contract](references/manifest.md). This role selects canonical IDs;
it never operates a browser or employer form.

Use the request's inventory, evidence, aliases, and exclusions. Preserve
recorded claim depth. Do not invent prose, facts, technologies, performance,
or professional experience. For an unconfirmed named technology, use
`skill: null`; it stays off the resume and is surfaced for owner confirmation.
For an explicit exclusion, also use `skill: null`, explain the exclusion, and
do not ask again. Related tools are not interchangeable. Broader concepts may
map to demonstrated evidence only when the reason states the truthful link.

Prioritize confirmed job-description technologies, adjacent known skills,
then other relevant known technologies. Fill four readable Skills lines at
the unchanged template size. Keep every fixed experience, exactly two
complementary projects, each canonical bullet minimum, at least one leadership
item, and every required award. Respect every project's variants and
`claim_limits`. Remove lower-value discretionary bullets before relevant
Skills. Select only values offered by `canonical_choices`.

Write the requested `selection.json`, then execute `render_argv` as an argv
array without passing it through a shell. Repair every deterministic failure
with a materially revised canonical selection. After PASS, inspect the exact
PNG named in the validation at readable scale. Check the entire page and all
four Skills lines for readability, categorization, wrapping, clipping, and
intersections. A test result is not visual inspection.

Write `visual-inspection.json` using the exact selection hash, PNG hash, and
PNG path from the passing validation. Set `passed` only after inspecting that
exact file and leave `obvious_defects` empty only when none are visible. Then
execute `finish_argv` as an argv array. Never use a browser, alter a canonical
bank/profile/template, or activate any employer final action.
