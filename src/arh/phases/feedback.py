from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from ..io import load_prompt, render_prompt, request_structured
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..results import (
    append_feedback_row,
    ensure_results_file,
    find_pending_feedback_exp_id,
    read_research_rows,
)
from ..schema import FeedbackSummary, load_contract_markdown


def read_log_tail(log_path: Path, max_lines: int = 80) -> str:
    if not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-max_lines:])


def parse_result_marker(log_path: Path) -> dict[str, str]:
    if not log_path.exists():
        return {}
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        if not line.startswith("ARH_RESULT"):
            continue
        payload: dict[str, str] = {}
        for token in line[len("ARH_RESULT") :].strip().split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            payload[key.strip()] = value.strip()
        return payload
    return {}


def tmux_session_exists(session_name: str, cwd: Path) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def find_log_path(cwd: Path, exp_id: int) -> Path | None:
    direct = cwd / ".autoresearch" / "logs" / f"exp{exp_id}_run.log"
    return direct if direct.exists() else None


def build_feedback_prompt(
    contract_markdown: str,
    results_markdown: str,
    research_row: dict[str, str],
    log_tail: str,
    result_marker: dict[str, str],
) -> str:
    template = load_prompt("feedback.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        results_markdown=results_markdown,
        research_row_json=json.dumps(research_row, ensure_ascii=False, indent=2),
        log_tail=log_tail or "(none)",
        result_marker_json=json.dumps(result_marker, ensure_ascii=False, indent=2),
    )


def run(
    cwd: Path,
    contract_path: str = "research.md",
    results_path: str = "results.md",
    exp_id: int | None = None,
    host: str = "127.0.0.1",
    port: int = 4096,
    model: str | None = None,
    verbose: bool = False,
) -> dict[str, object]:
    def append_error_entry(error_file: Path, exp_id_value: int, summary: str) -> None:
        if not summary.strip():
            return
        prefix = f"- exp_id={exp_id_value}: {summary.strip()}"
        if error_file.exists():
            existing = error_file.read_text(encoding="utf-8", errors="ignore").rstrip()
            error_file.write_text(
                (existing + "\n" + prefix + "\n").lstrip(), encoding="utf-8"
            )
            return
        error_file.write_text("# ERROR LOG\n" + prefix + "\n", encoding="utf-8")

    contract_file = cwd / contract_path
    if not contract_file.exists():
        raise FileNotFoundError(f"contract file not found: {contract_file}")

    results_file = cwd / results_path
    ensure_results_file(results_file)
    target_exp_id = exp_id or find_pending_feedback_exp_id(results_file)
    if target_exp_id is None:
        return {"status": "no_pending_experiment"}

    research_rows = read_research_rows(results_file)
    research_row = next(
        (row for row in research_rows if int(row["exp_id"]) == target_exp_id),
        None,
    )
    if research_row is None:
        raise RuntimeError(f"research row not found for exp_id={target_exp_id}")

    session_name = research_row["tmux_session_name"]
    if tmux_session_exists(session_name, cwd):
        return {
            "status": "running",
            "suggested_sleep_sec": 300,
            "exp_id": target_exp_id,
            "tmux_session_name": session_name,
        }

    log_path = find_log_path(cwd, target_exp_id)
    if log_path is None:
        return {"status": "missing_log", "exp_id": target_exp_id}

    contract_markdown = contract_file.read_text(encoding="utf-8", errors="ignore")
    results_markdown = results_file.read_text(encoding="utf-8", errors="ignore")
    result_marker = parse_result_marker(log_path)
    log_tail = read_log_tail(log_path)

    parsed = urlparse(f"http://{host}:{port}")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    process = start_server(host=host, port=port)
    try:
        wait_for_health(base_url)
        session = create_session(base_url, title=f"arh feedback {target_exp_id}")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")

        summary = request_structured(
            base_url=base_url,
            session_id=session_id,
            prompt=build_feedback_prompt(
                contract_markdown,
                results_markdown,
                research_row,
                log_tail,
                result_marker,
            ),
            model_type=FeedbackSummary,
            model=model,
            verbose=verbose,
            status_hint="Summarizing experiment feedback...",
        )

        append_feedback_row(
            results_file,
            target_exp_id,
            summary.main_metric,
            summary.sub_metric,
            summary.status,
            summary.description,
        )

        if summary.record_error:
            append_error_entry(
                cwd / "error.md",
                target_exp_id,
                summary.error_summary or summary.description,
            )

        return {
            "status": "completed",
            "session_id": session_id,
            "exp_id": target_exp_id,
            "summary": summary,
            "log_path": str(log_path),
            "result_marker": result_marker,
        }
    finally:
        stop_process(process)
