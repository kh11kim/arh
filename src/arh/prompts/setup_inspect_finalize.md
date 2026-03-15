You are finalizing the smoke inspection from the full conversation so far.

Your job:
1. Return a compact file-tree-style view around the entrypoint.
2. Return a short key-file list where each item is `path - one line description`.
3. Propose the minimal set of files that may need changes for ARH setup.
4. Propose the modifiable parameter scope based on the code and contract.
5. Propose a repo-relative smoke command.
6. Explain how the entrypoint should print `ARH_RUN_START ...` and `ARH_RESULT ...` with minimal code changes.

Rules:
- Return only the structured inspection result.
- Keep every field concise and practical.
- Keep `model_summary` as a short execution summary with 2-4 compact clauses: entrypoint flow, train/val flow, main validation metric.
- Keep `modifiable_files` to short path-focused items. Add a brief reason only when helpful.
- Keep `modifiable_parameters` grouped into a few concise categories that read well in terminal output. Prefer `category: item1, item2, item3`.
- Minimal ARH setup instrumentation is always allowed when needed for smoke setup.
- Always assume marker lines use space-separated `key=value` tokens, not JSON.
- Use this marker convention exactly:
  - `ARH_RUN_START exp=<run_label> pid=<pid>`
  - `ARH_RESULT exp=<run_label> metric=<metric_tag> value=<metric_value> status=completed`
  - `ARH_RESULT exp=<run_label> status=failed error=<short_error>`
- Set `ready_for_confirmation=true` only when the entrypoint, file tree, key files, file scope, parameter scope, smoke command, and entrypoint patch plan are all concrete enough for the user to confirm.

Current contract markdown:
{{contract_markdown}}
