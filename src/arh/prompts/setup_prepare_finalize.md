You are finalizing the smoke preparation plan from the full conversation so far.

Rules:
- Return only the structured preparation result.
- Do not propose multi-run experiments or broader research directions.
- Keep the plan focused on minimal smoke setup changes only.
- `changed_files` should be the minimal file list needed for smoke setup.
- `smoke_command` should be the exact repo-relative smoke command to run.
- `patch_plan` should briefly describe the marker/metric/env wiring changes only.
- Set `ready_for_confirmation=true` only when the smoke preparation plan is concrete enough to confirm.

Current contract markdown:
{{contract_markdown}}

Confirmed inspection JSON:
{{inspection_json}}
