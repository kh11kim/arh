You are in the FEEDBACK PHASE.

Your job in this phase is to inspect the latest finished run, extract the key result, and prepare clean context for the next work phase.

Procedure and responsibilities:
1. Inspect the latest experiment entry in `results.md` and the final log tail.
2. Extract the key result and produce a short feedback summary.
3. Judge the outcome relative to previous logged experiments.
4. If the metric improved, set `status=keep`.
5. If the metric is equal or worse, set `status=discard` and identify the accepted commit if possible.
6. If the run crashed or timed out, summarize the failure factually.
7. If the failure is operationally important or repeated, set `record_error=true` and provide a short `error_summary`.
8. Keep the result summary short and factual.
9. If the result is ambiguous, record the uncertainty instead of overstating confidence.

Rules:
- Do not make a new experimental change in this phase.
- Do not launch a new run in this phase.
- `main_metric` should be the numeric main metric value only, not the metric tag.
- `sub_metric` should be a numeric value if available, otherwise the literal string `null`.
- `status` for a finished run should be one of `keep`, `discard`, or `crash`.
- `next_phase` should usually be `research` after a finished run.
- `description` should be a short one-line summary, preferably under 120 characters.
- Avoid repeating full background context; mention only the result, comparison, and decision.

Current contract markdown:
{{contract_markdown}}

Current results markdown:
{{results_markdown}}

Research row JSON:
{{research_row_json}}

Latest log tail:
{{log_tail}}

Parsed result marker JSON:
{{result_marker_json}}
