from __future__ import annotations

import re
import time
from pathlib import Path

from ..io import load_prompt, render_prompt, request_structured
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..results import read_feedback_rows
from ..schema import LoopFinalSummary, load_contract_markdown
from . import feedback as feedback_phase
from . import research as research_phase


def _short(text: object, limit: int = 120) -> str:
    value = str(text).replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _parse_max_runs(stop_condition: str) -> int | None:
    text = str(stop_condition).strip().lower()
    if not text or text in {"infinite", "무한 실행", "none", "no stop condition"}:
        return None

    patterns = [
        r"(?:max\s*)?(\d+)\s*(?:runs?|experiments?|trials?)",
        r"(\d+)\s*(?:회|번)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _build_loop_summary_prompt(contract_markdown: str, results_markdown: str) -> str:
    template = load_prompt("research_loop_summary.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        results_markdown=results_markdown,
    )


def _generate_final_summary(
    *,
    cwd: Path,
    contract_path: str,
    results_path: str,
    host: str,
    port: int,
    model: str | None,
    verbose: bool,
) -> str:
    contract_markdown = (cwd / contract_path).read_text(
        encoding="utf-8", errors="ignore"
    )
    results_markdown = (cwd / results_path).read_text(encoding="utf-8", errors="ignore")
    base_url = f"http://{host}:{port}"
    process = start_server(host=host, port=port)
    try:
        wait_for_health(base_url)
        session = create_session(base_url, title="arh research loop summary")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")
        summary = request_structured(
            base_url=base_url,
            session_id=session_id,
            prompt=_build_loop_summary_prompt(contract_markdown, results_markdown),
            model_type=LoopFinalSummary,
            model=model,
            verbose=verbose,
            status_hint="Summarizing loop outcome...",
        )
        return summary.summary
    finally:
        stop_process(process)


def run(
    cwd: Path,
    contract_path: str = "research.md",
    results_path: str = "results.md",
    host: str = "127.0.0.1",
    port: int = 4096,
    model: str | None = None,
    verbose: bool = False,
    max_cycles: int = 0,
) -> dict[str, object]:
    cycle = 0
    last_message = ""
    completed_summaries: list[str] = []
    contract = load_contract_markdown(cwd / contract_path)
    max_runs = _parse_max_runs(contract.stop_condition)

    def emit(message: str) -> None:
        nonlocal last_message
        if message and message != last_message:
            print(message)
            last_message = message

    while True:
        cycle += 1
        if max_cycles > 0 and cycle > max_cycles:
            final_summary = _generate_final_summary(
                cwd=cwd,
                contract_path=contract_path,
                results_path=results_path,
                host=host,
                port=port,
                model=model,
                verbose=verbose,
            )
            return {
                "status": "stopped",
                "reason": "max_cycles",
                "cycles": cycle - 1,
                "final_summary": final_summary,
            }

        feedback = feedback_phase.run(
            cwd,
            contract_path=contract_path,
            results_path=results_path,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
        )
        if feedback.get("status") == "running":
            sleep_sec = int(feedback.get("suggested_sleep_sec", 300))
            exp_id = feedback.get("exp_id", "?")
            emit(f"[exp{exp_id}] feedback wait: checking again in {sleep_sec}s")
            time.sleep(sleep_sec)
            continue
        if feedback.get("status") == "completed":
            exp_id = feedback.get("exp_id", "?")
            summary = feedback.get("summary")
            if summary is not None:
                status_word = getattr(summary, "status", "completed")
                line = f"[exp{exp_id}] feedback {status_word}: {_short(getattr(summary, 'description', ''))}"
                emit(line)
                completed_summaries.append(line)
            if max_runs is not None:
                completed_runs = len(read_feedback_rows(cwd / results_path))
                if completed_runs >= max_runs:
                    final_summary = _generate_final_summary(
                        cwd=cwd,
                        contract_path=contract_path,
                        results_path=results_path,
                        host=host,
                        port=port,
                        model=model,
                        verbose=verbose,
                    )
                    return {
                        "status": "stopped",
                        "reason": "stop_condition",
                        "stop_condition": contract.stop_condition,
                        "completed_runs": completed_runs,
                        "cycles": completed_runs,
                        "final_summary": final_summary,
                    }
        if feedback.get("status") not in {"completed", "no_pending_experiment"}:
            feedback["cycles"] = cycle
            if completed_summaries:
                feedback["final_summary"] = completed_summaries[-1]
            return feedback

        research = research_phase.run(
            cwd,
            contract_path=contract_path,
            results_path=results_path,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
        )
        if research.get("status") in {"launched", "waiting"}:
            sleep_sec = int(research.get("polling_interval_seconds", 300))
            exp_id = research.get("exp_id", "?")
            if research.get("status") == "launched":
                plan = research.get("plan")
                hypothesis = getattr(plan, "hypothesis", "") if plan is not None else ""
                emit(f"[exp{exp_id}] research launch: {_short(hypothesis)}")
            else:
                emit(f"[exp{exp_id}] research wait: checking again in {sleep_sec}s")
            time.sleep(sleep_sec)
            continue

        research["cycles"] = cycle
        if completed_summaries:
            research["final_summary"] = completed_summaries[-1]
        return research
