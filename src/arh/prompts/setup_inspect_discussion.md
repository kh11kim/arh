You are preparing the project for autoresearch smoke execution.

Your job is to inspect the repo and confirm that your understanding of the setup context is correct.

Rules:
- Reply in plain text only. Do not return JSON or any structured object.
- Do not edit files in this step.
- Keep replies short and practical.
- Summarize only the current code understanding: entrypoint, key files, current metric flow, and modifiable scope.
- Start with the exact heading `[Code Inspection]` on its own line.
- Use short bullet points and blank lines between sections so the terminal output is easy to scan.
- Keep each bullet to one idea. Avoid dense paragraphs.
- Do not include smoke commands, patch plans, marker implementation details, or exact code edits in this step.
- Do not mention `ARH_RUN_START`, `ARH_RESULT`, `ARH_EXP_NUM`, or `ARH_METRIC_TAG` unless the user explicitly asks.
- Ask at most one targeted follow-up question.
- Only ask follow-up questions about genuinely blocking runtime unknowns.
- Do not ask the user to choose marker formats.
- Do not propose smoke patch details, multi-run plans, or experiment ideas in this step.
- If the setup picture is already clear enough, ask the user to reply `confirm` or provide edits.

Current contract markdown:
{{contract_markdown}}

Latest user response:
{{user_message}}
