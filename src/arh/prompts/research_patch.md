You are preparing the code for the next autoresearch experiment.

Your job:
1. Apply the minimum code/config changes needed to implement the hypothesis.
2. Preserve the existing ARH setup instrumentation.
3. Do not launch the run yourself. The harness will launch it after you finish.

Rules:
- Keep changes within the contract.
- Keep changes minimal and reversible.
- If launch previously failed, use the log tail to fix the issue before the next launch attempt.
- If the issue requires user action, environment setup, credentials, missing data, or ambiguous project decisions, do not guess. Return `status=needs_user_action` with a clear action request.
- Do not mix multiple major ideas in one run.
- Large changes are allowed, but complexity is not justified by marginal gains.
- If two approaches perform similarly, prefer the simpler one.
- Do not evaluate final results in this phase.

Current contract markdown:
{{contract_markdown}}

Current results markdown:
{{results_markdown}}

Research plan JSON:
{{plan_json}}

Previous patch result JSON:
{{previous_patch_json}}

Latest launch verification log tail:
{{log_tail}}
