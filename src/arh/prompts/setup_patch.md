You are applying the ARH setup patch after the user confirmed the inspection.

Your goals:
- Edit the minimum number of files needed.
- Keep the existing training entrypoint and command structure intact.
- Make the training entrypoint emit machine-readable markers.
- After patching, assume the harness will run the smoke command. If it fails and a log tail is provided, use that failure context to make the next minimal fix.
- Keep iterating toward a successful smoke run.
- If the issue requires user action, environment setup, credentials, missing data, or ambiguous project decisions, do not guess. Return `status=needs_user_action` with a clear action request.

Required markers:
- Near run start: `ARH_RUN_START exp={{run_label}} pid=<pid>`
- At the end of entrypoint execution on success: `ARH_RESULT exp={{run_label}} metric=<metric_tag> value=<metric_value> status=completed`
- If practical with minimal change, emit `ARH_RESULT exp={{run_label}} status=failed error=<short_error>` before re-raising on fatal failure.

Implementation preferences:
- Prefer entrypoint-end printing instead of deeply invasive changes.
- Prefer reading `ARH_EXP_NUM` and `ARH_METRIC_TAG` from environment variables when needed.
- Do not add broad new interfaces unless truly necessary.
- Keep changes within the confirmed modifiable file scope whenever possible.
- Treat minimal ARH setup instrumentation as allowed even when it touches the training entrypoint outside the research/search modification scope.
- Do not ask the user to widen the contract only to allow `ARH_RUN_START` / `ARH_RESULT` prints or tiny metric plumbing needed for smoke setup.

After editing files, return a concise structured summary of what changed.

Current contract markdown:
{{contract_markdown}}

Confirmed inspection JSON:
{{inspection_json}}

Runtime values:
- run_label={{run_label}}
- metric_tag={{metric_tag}}

Previous patch result JSON:
{{previous_patch_json}}

Latest smoke log tail:
{{log_tail}}
