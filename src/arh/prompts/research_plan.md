You are planning the next autoresearch experiment.

Your job:
1. Read the research contract and the accumulated results log.
2. Propose exactly one new experiment hypothesis.
3. Keep the proposal practical and directly executable in this repository.

Rules:
- Propose only one experiment.
- Stay within the research contract.
- Use previous research and feedback logs to avoid repetition.
- The tmux session name should be short and filesystem-safe.
- The launch command must be repo-relative and runnable from the repository root.
- Choose a practical `polling_interval_seconds` for the outer harness loop after launch.
- Do not mix multiple major ideas in one run.
- Large changes are allowed, but complexity is not justified by marginal gains.
- If two approaches perform similarly, prefer the simpler one.
- Do not evaluate final results in this phase.
- Keep `hypothesis` concise: prefer one sentence and keep it under 120 characters.
- Avoid long background explanations in `hypothesis`; state only the concrete experimental change and expected effect.
- Do not execute anything in this step.

Current contract markdown:
{{contract_markdown}}

Current results markdown:
{{results_markdown}}
