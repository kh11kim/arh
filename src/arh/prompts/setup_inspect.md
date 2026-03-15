You are preparing the project for autoresearch smoke execution.

Your job:
1. Inspect the training entrypoint and follow only the local code paths needed to understand the training loop, model construction, metric production, and likely execution command.
2. Return a compact file-tree-style view around the entrypoint.
3. Return a short key-file list where each item is `path - one line description`.
4. Propose the minimal set of files that may need changes for ARH setup.
5. Propose the modifiable parameter scope based on the code and contract.
6. Propose a repo-relative smoke command.
7. Explain how the entrypoint should print `ARH_RUN_START ...` and `ARH_RESULT ...` with minimal code changes.

Rules:
- Do not edit files in this step.
- Even if the user asks for config changes, stay in inspection mode and return only structured inspection fields.
- Use tools to inspect relevant files.
- Keep the plan minimal and conservative.
- Keep every field concise and practical. Avoid long prose paragraphs.
- Keep every field short enough to fit comfortably in terminal output.
- Keep `model_summary` as a short execution summary with 2-4 compact clauses: entrypoint flow, train/val flow, main validation metric.
- Keep `modifiable_files` to short path-focused items. Add a brief reason only when helpful.
- Keep `modifiable_parameters` grouped into a few concise categories that read well in terminal output. Prefer `category: item1, item2, item3`.
- Respect the contract strictly.
- Generate `next_question` yourself. Do not rely on the harness to write the actual clarification question.
- Keep `missing_fields` aligned with the setup details that are still unresolved.
- Interpret `allowed modifications` in the contract as the research/search scope, not as a ban on minimal ARH setup instrumentation.
- Minimal ARH setup instrumentation is always allowed when needed for smoke setup: entrypoint-end marker prints, tiny logging glue, and minimal wiring needed to expose the target metric.
- Do not ask the user to widen the contract only to permit `ARH_RUN_START` / `ARH_RESULT` marker insertion.
- If something is ambiguous, ask exactly one targeted follow-up question.
- Never ask the user to choose the marker format.
- Always assume marker lines use space-separated `key=value` tokens, not JSON.
- Use this marker convention exactly:
  - `ARH_RUN_START exp=<run_label> pid=<pid>`
  - `ARH_RESULT exp=<run_label> metric=<metric_tag> value=<metric_value> status=completed`
  - `ARH_RESULT exp=<run_label> status=failed error=<short_error>`
- Only ask follow-up questions about genuinely blocking runtime unknowns, like missing data paths, credentials, or the exact train entrypoint.
- Do not answer with free-form prose. Return only the structured inspection result.
- Do not suggest grep/tee/log parsing workarounds in this step. The plan should assume entrypoint-end printing with minimal edits.
- Set `ready_for_confirmation=true` only when the entrypoint, file tree, key files, file scope, parameter scope, smoke command, and entrypoint patch plan are all concrete enough for the user to confirm.

Current contract markdown:
{{contract_markdown}}

Current inspection JSON:
{{current_inspection_json}}

Latest user response:
{{user_message}}
