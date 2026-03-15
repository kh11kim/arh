You are finalizing the research contract from the full conversation so far.

Rules:
- Return only the final structured contract state.
- Do not ask follow-up questions unless information is still missing.
- Infer from the conversation when safe, but do not invent or silently expand scope.
- For evaluation metrics, prefer short metric tags or identifiers rather than prose descriptions.
- The `direction` field must resolve to exactly one of: `maximize` or `minimize`.
- `experiment_time` is the time budget for one experiment run.
- `train_entrypoint` must be a repo-relative file path, not a shell command.
- `stop_condition` is for the overall autoresearch loop, not for a single training run.
- Do not auto-fill allowed modifications beyond what the user actually allowed.
- Do not auto-fill forbidden modifications unless the user explicitly says them, or explicitly confirms that forbidden modifications should be `everything else`.
- Keep `missing_fields` aligned with the fields that are still unresolved.
- You may set `ready_for_review` to true only when all of these are clear:
  - research goal
  - main metric
  - metric direction
  - per-experiment execution time budget
  - train entrypoint file
  - stop condition, or explicit `infinite`
  - allowed modifications
  - forbidden modifications or explicit confirmation of `everything else`
- `tie_breaker` is optional. If the user does not care, set it to `None`.
- When ready for review, `next_question` should ask the user to reply `confirm` or provide edits.

Return the full current contract state.
