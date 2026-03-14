from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from ..io import load_prompt, render_prompt, request_structured
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..results import (
    append_research_row,
    ensure_results_file,
    next_research_exp_id,
    read_research_rows,
)
from ..schema import (
    ContractState,
    ResearchPatchResult,
    ResearchPlan,
    load_contract_markdown,
)


def build_plan_prompt(contract_markdown: str, results_markdown: str) -> str:
    template = load_prompt("research_plan.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        results_markdown=results_markdown,
    )


def build_patch_prompt(
    contract_markdown: str,
    results_markdown: str,
    plan: ResearchPlan,
    previous_patch_result: ResearchPatchResult | None,
    log_tail: str,
) -> str:
    template = load_prompt("research_patch.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        results_markdown=results_markdown,
        plan_json=plan.model_dump_json(indent=2),
        previous_patch_json=(
            previous_patch_result.model_dump_json(indent=2)
            if previous_patch_result is not None
            else "(none)"
        ),
        log_tail=log_tail or "(none)",
    )


def logs_dir(cwd: Path) -> Path:
    path = cwd / ".autoresearch" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_session_name(value: str, exp_id: int) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip()
    )
    cleaned = cleaned.strip("-")
    return cleaned or f"arh-exp-{exp_id}"


def read_log_tail(log_path: Path, max_lines: int = 60) -> str:
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


def kill_tmux_session(session_name: str, cwd: Path) -> None:
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def launch_tmux_run(
    *,
    cwd: Path,
    session_name: str,
    command: str,
    exp_id: int,
    metric_tag: str,
) -> dict[str, str]:
    log_path = logs_dir(cwd) / f"exp{exp_id}_run.log"
    env_prefix = " ".join(
        [
            f"ARH_EXP_NUM={shlex.quote(str(exp_id))}",
            f"ARH_METRIC_TAG={shlex.quote(metric_tag)}",
            "ARH_SMOKE=0",
        ]
    )
    wrapped = f"cd {shlex.quote(str(cwd))} && {env_prefix} {command} > {shlex.quote(str(log_path))} 2>&1"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, wrapped],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "tmux_session_name": session_name,
        "log_path": str(log_path),
        "command": command,
    }


def verify_launch(
    cwd: Path, session_name: str, log_path: Path, wait_seconds: float = 2.0
) -> tuple[bool, str]:
    time.sleep(wait_seconds)
    alive = tmux_session_exists(session_name, cwd)
    if alive:
        return True, "tmux session is alive"
    tail = read_log_tail(log_path)
    return False, tail or "tmux session exited before verification"


def git_is_repo(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def commit_research_changes(
    cwd: Path,
    changed_files: list[str],
    exp_id: int,
    hypothesis: str,
    attempt: int,
) -> str:
    if not git_is_repo(cwd):
        raise RuntimeError("git repository required for research phase")

    existing: list[str] = []
    for item in changed_files:
        path = Path(item)
        resolved = path if path.is_absolute() else (cwd / path)
        if resolved.exists():
            try:
                existing.append(str(resolved.relative_to(cwd)))
            except ValueError:
                existing.append(str(resolved))

    if existing:
        subprocess.run(
            ["git", "add", "--", *existing],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
        status = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            title = hypothesis.strip().splitlines()[0][:60]
            message = (
                f"Research exp {exp_id}.{attempt}: {title}"
                if title
                else f"Research exp {exp_id}.{attempt}"
            )
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(cwd),
                check=True,
                capture_output=True,
                text=True,
            )

    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return head.stdout.strip()


def run(
    cwd: Path,
    contract_path: str = "research.md",
    results_path: str = "results.md",
    host: str = "127.0.0.1",
    port: int = 4096,
    model: str | None = None,
    verbose: bool = False,
    max_launch_attempts: int = 3,
) -> dict[str, object]:
    contract_file = cwd / contract_path
    if not contract_file.exists():
        raise FileNotFoundError(f"contract file not found: {contract_file}")

    results_file = cwd / results_path
    ensure_results_file(results_file)

    contract_markdown = contract_file.read_text(encoding="utf-8", errors="ignore")
    contract = load_contract_markdown(contract_file)
    results_markdown = results_file.read_text(encoding="utf-8", errors="ignore")
    latest_rows = read_research_rows(results_file)
    if latest_rows:
        latest = latest_rows[-1]
        latest_session = latest["tmux_session_name"]
        if tmux_session_exists(latest_session, cwd):
            return {
                "status": "waiting",
                "exp_id": int(latest["exp_id"]),
                "tmux_session_name": latest_session,
                "commit": latest["commit"],
                "polling_interval_seconds": 300,
            }
    exp_id = next_research_exp_id(results_file)

    parsed = urlparse(f"http://{host}:{port}")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    process = start_server(host=host, port=port)
    try:
        wait_for_health(base_url)
        session = create_session(base_url, title=f"arh research {exp_id}")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")

        plan = request_structured(
            base_url=base_url,
            session_id=session_id,
            prompt=build_plan_prompt(contract_markdown, results_markdown),
            model_type=ResearchPlan,
            model=model,
            verbose=verbose,
            status_hint="Planning next experiment...",
        )

        patch_result: ResearchPatchResult | None = None
        launch_info: dict[str, str] | None = None
        commit_hash = ""
        log_tail = ""
        session_name = sanitize_session_name(plan.tmux_session_name, exp_id)

        for attempt in range(1, max_launch_attempts + 1):
            if tmux_session_exists(session_name, cwd):
                kill_tmux_session(session_name, cwd)

            patch_result = request_structured(
                base_url=base_url,
                session_id=session_id,
                prompt=build_patch_prompt(
                    contract_markdown,
                    results_markdown,
                    plan,
                    patch_result,
                    log_tail,
                ),
                model_type=ResearchPatchResult,
                model=model,
                verbose=verbose,
                status_hint="Preparing experiment changes...",
            )

            if patch_result.status == "needs_user_action":
                return {
                    "status": "needs_user_action",
                    "session_id": session_id,
                    "plan": plan,
                    "patch": patch_result,
                }

            command = patch_result.launch_command or plan.launch_command
            if not command:
                raise RuntimeError("launch command is empty")

            commit_hash = commit_research_changes(
                cwd,
                patch_result.changed_files,
                exp_id,
                plan.hypothesis,
                attempt,
            )

            launch_info = launch_tmux_run(
                cwd=cwd,
                session_name=session_name,
                command=command,
                exp_id=exp_id,
                metric_tag=contract.evaluation.main_metric,
            )
            ok, detail = verify_launch(cwd, session_name, Path(launch_info["log_path"]))
            if ok:
                append_research_row(
                    results_file,
                    exp_id,
                    session_name,
                    commit_hash,
                    plan.hypothesis,
                )
                return {
                    "status": "launched",
                    "session_id": session_id,
                    "exp_id": exp_id,
                    "plan": plan,
                    "patch": patch_result,
                    "launch": launch_info,
                    "commit": commit_hash,
                    "polling_interval_seconds": plan.polling_interval_seconds,
                }
            log_tail = detail

        return {
            "status": "failed",
            "session_id": session_id,
            "exp_id": exp_id,
            "plan": plan,
            "patch": patch_result,
            "launch": launch_info,
            "commit": commit_hash,
            "polling_interval_seconds": plan.polling_interval_seconds,
            "log_tail": log_tail,
        }
    finally:
        stop_process(process)
