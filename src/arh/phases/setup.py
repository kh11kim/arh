from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from ..io import load_prompt, render_prompt, request_structured
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..schema import (
    DEFAULT_RESEARCH_MD,
    ContractState,
    SmokeInspection,
    SetupPatchResult,
    load_contract_markdown,
    sanitize_model_text,
)


RESULT_PREFIX = "ARH_RESULT"
START_PREFIX = "ARH_RUN_START"


def sanitize_user_input(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned.strip()


def logs_dir(cwd: Path) -> Path:
    path = cwd / ".autoresearch" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_duration_seconds(value: str) -> int:
    raw = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(s|sec|secs|m|min|mins|h|hr|hrs)", raw)
    if not match:
        return 600
    amount = int(match.group(1))
    unit = match.group(2)
    if unit in {"s", "sec", "secs"}:
        return amount
    if unit in {"m", "min", "mins"}:
        return amount * 60
    return amount * 3600


def build_inspect_prompt(
    contract_markdown: str,
    current_inspection: SmokeInspection,
    user_message: str,
) -> str:
    template = load_prompt("setup_inspect.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        current_inspection_json=current_inspection.model_dump_json(indent=2),
        user_message=user_message.strip(),
    )


def build_patch_prompt(
    contract_markdown: str,
    inspection: SmokeInspection,
    run_label: str,
    metric_tag: str,
    previous_patch_result: SetupPatchResult | None,
    log_tail: str,
) -> str:
    template = load_prompt("setup_patch.md")
    return render_prompt(
        template,
        contract_markdown=contract_markdown,
        inspection_json=inspection.model_dump_json(indent=2),
        run_label=str(run_label),
        metric_tag=metric_tag,
        previous_patch_json=(
            previous_patch_result.model_dump_json(indent=2)
            if previous_patch_result is not None
            else "(none)"
        ),
        log_tail=log_tail or "(none)",
    )


def print_inspection(inspection: SmokeInspection) -> None:
    print("\nSmoke inspection:\n")
    print(f"- entrypoint: {inspection.entrypoint or '(not set)'}")
    print("- file_tree:")
    for item in inspection.file_tree or ["(not set)"]:
        print(f"  {item}")
    print("- key_files:")
    for item in inspection.key_files or ["(not set)"]:
        print(f"  {item}")
    print(f"- model: {inspection.model_summary or '(not set)'}")
    print(f"- files: {', '.join(inspection.modifiable_files) or '(not set)'}")
    print(f"- parameters: {', '.join(inspection.modifiable_parameters) or '(not set)'}")
    print()


def request_inspection(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    current_inspection: SmokeInspection,
    user_message: str,
    model: str | None,
    verbose: bool,
) -> SmokeInspection:
    prompt = build_inspect_prompt(
        contract_markdown=contract_markdown,
        current_inspection=current_inspection,
        user_message=user_message,
    )
    return request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model_type=SmokeInspection,
        model=model,
        verbose=verbose,
        status_hint="Inspecting training code...",
    )


def request_patch(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    inspection: SmokeInspection,
    run_label: str,
    metric_tag: str,
    previous_patch_result: SetupPatchResult | None,
    log_tail: str,
    model: str | None,
    verbose: bool,
) -> SetupPatchResult:
    prompt = build_patch_prompt(
        contract_markdown=contract_markdown,
        inspection=inspection,
        run_label=run_label,
        metric_tag=metric_tag,
        previous_patch_result=previous_patch_result,
        log_tail=log_tail,
    )
    return request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model_type=SetupPatchResult,
        model=model,
        verbose=verbose,
        status_hint="Applying smoke patch...",
    )


def sanitize_inspection(inspection: SmokeInspection) -> SmokeInspection:
    cleaned = inspection.model_copy(deep=True)
    cleaned.entrypoint = sanitize_model_text(cleaned.entrypoint)
    cleaned.file_tree = [
        sanitize_model_text(item)
        for item in cleaned.file_tree
        if sanitize_model_text(item)
    ]
    cleaned.key_files = [
        sanitize_model_text(item)
        for item in cleaned.key_files
        if sanitize_model_text(item)
    ]
    cleaned.model_summary = sanitize_model_text(cleaned.model_summary)
    cleaned.modifiable_files = [
        sanitize_model_text(item)
        for item in cleaned.modifiable_files
        if sanitize_model_text(item)
    ]
    cleaned.modifiable_parameters = [
        sanitize_model_text(item)
        for item in cleaned.modifiable_parameters
        if sanitize_model_text(item)
    ]
    cleaned.smoke_command = sanitize_model_text(cleaned.smoke_command)
    cleaned.entrypoint_patch_plan = sanitize_model_text(cleaned.entrypoint_patch_plan)
    cleaned.next_question = sanitize_model_text(cleaned.next_question)
    return cleaned


def update_contract_with_inspection(
    contract_file: Path, inspection: SmokeInspection
) -> None:
    base = contract_file.read_text(encoding="utf-8", errors="ignore").rstrip()
    marker = "\n# Setup Inspection\n"
    if marker in base:
        base = base.split(marker, 1)[0].rstrip()

    lines = [
        base,
        "",
        "# Setup Inspection",
        f"- entrypoint: {inspection.entrypoint}",
        "- file_tree:",
    ]
    lines.extend([f"  - {item}" for item in inspection.file_tree])
    lines.append("- key_files:")
    lines.extend([f"  - {item}" for item in inspection.key_files])
    lines.append(f"- model_summary: {inspection.model_summary}")
    lines.append(f"- modifiable_files: {', '.join(inspection.modifiable_files)}")
    lines.append(
        f"- modifiable_parameters: {', '.join(inspection.modifiable_parameters)}"
    )
    lines.append(f"- smoke_command: {inspection.smoke_command}")
    lines.append(f"- entrypoint_patch_plan: {inspection.entrypoint_patch_plan}")
    contract_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_smoke_command(
    *,
    cwd: Path,
    command: str,
    run_label: str,
    timeout_seconds: int,
    metric_tag: str,
) -> dict[str, object]:
    temp_log_path = logs_dir(cwd) / "setup_smoke_pending.log"
    with temp_log_path.open("w", encoding="utf-8") as log_handle:
        env = os.environ.copy()
        env["ARH_EXP_NUM"] = str(run_label)
        env["ARH_METRIC_TAG"] = metric_tag
        env["ARH_SMOKE"] = "1"
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            shell=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        final_log_path = logs_dir(cwd) / "setup_smoke.log"
        if final_log_path.exists():
            final_log_path.unlink()
        temp_log_path.rename(final_log_path)
        timed_out = False
        start_time = time.time()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            exit_code = process.returncode or -1
            log_handle.write("\nARH_RESULT status=timeout\n")

    return {
        "command": command,
        "log_path": str(final_log_path),
        "pid": process.pid,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - start_time, 2),
    }


def read_log_tail(log_path: Path, max_lines: int = 60) -> str:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-max_lines:])


def parse_result_marker(log_path: Path) -> dict[str, str]:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        if not line.startswith(RESULT_PREFIX):
            continue
        payload: dict[str, str] = {}
        for token in line[len(RESULT_PREFIX) :].strip().split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            payload[key.strip()] = value.strip()
        return payload
    return {}


def git_is_repo(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def commit_and_tag(cwd: Path, changed_files: list[str]) -> dict[str, str]:
    existing: list[str] = []
    for item in changed_files:
        path = Path(item)
        resolved = path if path.is_absolute() else (cwd / path)
        if resolved.exists():
            try:
                existing.append(str(resolved.relative_to(cwd)))
            except ValueError:
                existing.append(str(resolved))
    if not git_is_repo(cwd) or not existing:
        return {"commit": "skipped", "tag": "skipped"}

    subprocess.run(
        ["git", "add", "--", *existing],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initialize ARH smoke setup"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )

    tag_name = "init/setup-smoke"
    existing_tags = subprocess.run(
        ["git", "tag", "--list", tag_name],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    if existing_tags.stdout.strip():
        tag_name = f"init/setup-smoke-{int(time.time())}"
    subprocess.run(["git", "tag", tag_name], cwd=str(cwd), check=True)
    return {"commit": "created", "tag": tag_name}


def run(
    cwd: Path,
    contract_path: str = DEFAULT_RESEARCH_MD,
    host: str = "127.0.0.1",
    port: int = 4096,
    model: str | None = None,
    verbose: bool = False,
    max_fix_attempts: int = 2,
) -> dict[str, object]:
    contract_file = cwd / contract_path
    if not contract_file.exists():
        raise FileNotFoundError(f"contract file not found: {contract_file}")

    contract_markdown = contract_file.read_text(encoding="utf-8", errors="ignore")
    contract = load_contract_markdown(contract_file)

    parsed = urlparse(f"http://{host}:{port}")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    process = start_server(host=host, port=port)

    try:
        wait_for_health(base_url)
        session = create_session(base_url, title="arh setup")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")

        print("OpenCode setup session started.")

        inspection = SmokeInspection()
        user_message = (
            "Inspect the training entrypoint and prepare a minimal smoke setup plan."
        )
        while True:
            inspection = request_inspection(
                base_url=base_url,
                session_id=session_id,
                contract_markdown=contract_markdown,
                current_inspection=inspection,
                user_message=user_message,
                model=model,
                verbose=verbose,
            )
            print_inspection(inspection)
            print(inspection.next_question)
            try:
                user_input = sanitize_user_input(input("> "))
            except EOFError:
                user_input = "quit"

            if user_input.lower() == "quit":
                return {"status": "cancelled", "session_id": session_id}
            if inspection.ready_for_confirmation and user_input.lower() == "confirm":
                break
            user_message = user_input or "Please continue."

        inspection = sanitize_inspection(inspection)
        update_contract_with_inspection(contract_file, inspection)
        contract_markdown = contract_file.read_text(encoding="utf-8", errors="ignore")
        run_label = "setup"
        patch_result: SetupPatchResult | None = None
        smoke_result: dict[str, object] | None = None
        marker: dict[str, str] = {}
        attempts = 0
        changed_files: list[str] = []

        while attempts < max_fix_attempts + 1:
            patch_result = request_patch(
                base_url=base_url,
                session_id=session_id,
                contract_markdown=contract_markdown,
                inspection=inspection,
                run_label=run_label,
                metric_tag=contract.evaluation.main_metric,
                previous_patch_result=patch_result,
                log_tail=(
                    read_log_tail(Path(str(smoke_result["log_path"])))
                    if smoke_result is not None
                    else ""
                ),
                model=model,
                verbose=verbose,
            )

            print("\nApplied setup patch:")
            print(f"- summary: {patch_result.summary or '(no summary)'}")
            print(
                f"- changed_files: {', '.join(patch_result.changed_files) or '(none reported)'}"
            )

            if patch_result.status == "needs_user_action":
                print("\nUser action is required.")
                print(f"- summary: {patch_result.summary or '(none)'}")
                print(f"- action: {patch_result.user_action or '(none)'}")
                return {
                    "status": "needs_user_action",
                    "session_id": session_id,
                    "inspection": inspection,
                    "patch": patch_result,
                    "smoke_result": smoke_result,
                }

            changed_files.extend(patch_result.changed_files)
            smoke_result = run_smoke_command(
                cwd=cwd,
                command=inspection.smoke_command,
                run_label=run_label,
                timeout_seconds=parse_duration_seconds(
                    contract.execution.experiment_time
                ),
                metric_tag=contract.evaluation.main_metric,
            )
            marker = parse_result_marker(Path(str(smoke_result["log_path"])))
            if marker and marker.get("status") in {"completed", "success"}:
                break
            attempts += 1

        success = bool(marker) and marker.get("status") in {"completed", "success"}
        git_result = (
            commit_and_tag(cwd, list(dict.fromkeys(changed_files)))
            if success
            else {"commit": "skipped", "tag": "skipped"}
        )
        return {
            "status": "completed" if success else "failed",
            "session_id": session_id,
            "inspection": inspection,
            "patch": patch_result,
            "smoke_result": smoke_result,
            "result_marker": marker,
            "git": git_result,
        }
    finally:
        stop_process(process)
