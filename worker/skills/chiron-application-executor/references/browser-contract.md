# Browser helper quick reference

All functions are imported from the workspace-local `agent_helpers` module.

```python
observed = ats_observe(js, ats_family)
filled = trusted_batch_input(js, fill_input, assignments)
selected = exact_select(js, click_at_xy, ref, exact_value)
uploaded = upload_and_verify(js, cdp, ref, package_path)
advanced = advance(js, click_at_xy)
review = review_readback(js, ats_family, profile, constraints)
```

Every callback acts on the already selected target. For out-of-process frames,
attach through CDP and route methods with `session_id`; verify the frame geometry
before any trusted input.

Successful helper return values prove only the stated page mechanic. They do not
prove application delivery, submission, employer receipt, or human consent.
