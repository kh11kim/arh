You are preparing the project for autoresearch smoke execution.

Your job:
1. Inspect the training entrypoint and follow only the local code paths needed to understand the training loop, model construction, metric production, and likely execution command.
2. Return a compact file-tree-style view around the entrypoint.
3. Return a short key-file list where each item is `path - one line description`.
4. Propose the minimal set of files that may need changes for ARH setup.
5. Propose the modifiable parameter scope based on the code and contract.
6. Propose a repo-relative smoke command.
7. Explain how the entrypoint end should print `ARH_RUN_START ...` and `ARH_RESULT ...` with minimal code changes.

Rules:
- Do not edit files in this step.
- Use tools to inspect relevant files.
- Keep the plan minimal and conservative.
- Keep every field concise and practical. Avoid long prose paragraphs.
- Respect the contract strictly.
- Generate `next_question` yourself. Do not rely on the harness to write the actual clarification question.
- Keep `missing_fields` aligned with the setup details that are still unresolved.
- Interpret `allowed modifications` in the contract as the research/search scope, not as a ban on minimal ARH setup instrumentation.
- Minimal ARH setup instrumentation is always allowed when needed for smoke setup: entrypoint-end marker prints, tiny logging glue, and minimal wiring needed to expose the target metric.
- Do not ask the user to widen the contract only to permit `ARH_RUN_START` / `ARH_RESULT` marker insertion.
- If something is ambiguous, ask exactly one targeted follow-up question.
- Do not suggest grep/tee/log parsing workarounds in this step. The plan should assume entrypoint-end printing with minimal edits.
- Set `ready_for_confirmation=true` only when the entrypoint, file tree, key files, file scope, parameter scope, smoke command, and entrypoint patch plan are all concrete enough for the user to confirm.

Current contract markdown:
{{contract_markdown}}

Current inspection JSON:
{{current_inspection_json}}

Latest user response:
{{user_message}}
