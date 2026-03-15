from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import typer

from .. import io
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..schema import (
    DEFAULT_RESEARCH_MD,
    ContractState,
    SmokeInspection,
    SetupPreparation,
    SetupPatchResult,
    load_contract_markdown,
    sanitize_model_text,
)


RESULT_PREFIX = "ARH_RESULT"
START_PREFIX = "ARH_RUN_START"


def sanitize_user_input(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
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


def build_inspect_discussion_prompt(contract_markdown: str, user_message: str) -> str:
    template = io.load_prompt("setup_inspect_discussion.md")
    return io.render_prompt(
        template,
        contract_markdown=contract_markdown,
        user_message=user_message.strip(),
    )


def build_inspect_finalize_prompt(contract_markdown: str) -> str:
    template = io.load_prompt("setup_inspect_finalize.md")
    return io.render_prompt(template, contract_markdown=contract_markdown)


def build_prepare_discussion_prompt(
    contract_markdown: str, inspection: SmokeInspection, user_message: str
) -> str:
    template = io.load_prompt("setup_prepare_discussion.md")
    return io.render_prompt(
        template,
        contract_markdown=contract_markdown,
        inspection_json=inspection.model_dump_json(indent=2),
        user_message=user_message.strip(),
    )


def build_prepare_finalize_prompt(
    contract_markdown: str, inspection: SmokeInspection
) -> str:
    template = io.load_prompt("setup_prepare_finalize.md")
    return io.render_prompt(
        template,
        contract_markdown=contract_markdown,
        inspection_json=inspection.model_dump_json(indent=2),
    )


def build_patch_prompt(
    contract_markdown: str,
    inspection: SmokeInspection,
    preparation: SetupPreparation,
    run_label: str,
    metric_tag: str,
    previous_patch_result: SetupPatchResult | None,
    log_tail: str,
) -> str:
    template = io.load_prompt("setup_patch.md")
    return io.render_prompt(
        template,
        contract_markdown=contract_markdown,
        inspection_json=inspection.model_dump_json(indent=2),
        preparation_json=preparation.model_dump_json(indent=2),
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
    def print_list(title: str, items: list[str]) -> None:
        print(f"- {title}:")
        for item in items or ["(not set)"]:
            print(f"  {item}")

    print("\nSmoke inspection:\n")
    print(f"- entrypoint: {inspection.entrypoint or '(not set)'}")
    print_list("file_tree", inspection.file_tree)
    print_list("key_files", inspection.key_files)
    print(f"- experiment_summary: {inspection.model_summary or '(not set)'}")
    print_list("modifiable_scope", inspection.modifiable_files)
    print_list("tunable_scope", inspection.modifiable_parameters)
    print()


def print_preparation(preparation: SetupPreparation) -> None:
    print("\nSmoke preparation:\n")
    print(f"- summary: {preparation.preparation_summary or '(not set)'}")
    print("- changed_files:")
    for item in preparation.changed_files or ["(not set)"]:
        print(f"  {item}")
    print(f"- smoke_command: {preparation.smoke_command or '(not set)'}")
    print(f"- patch_plan: {preparation.patch_plan or '(not set)'}")
    print()


def request_inspection(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    user_message: str,
    model: str | None,
    verbose: bool,
) -> str:
    prompt = build_inspect_discussion_prompt(
        contract_markdown=contract_markdown, user_message=user_message
    )
    return io.request_text(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        verbose=verbose,
        status_hint="Discussing training inspection...",
    )


def finalize_inspection(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    model: str | None,
    verbose: bool,
) -> SmokeInspection:
    return io.request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=build_inspect_finalize_prompt(contract_markdown),
        model_type=SmokeInspection,
        model=model,
        verbose=verbose,
        status_hint="Finalizing training inspection...",
    )


def request_preparation(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    inspection: SmokeInspection,
    user_message: str,
    model: str | None,
    verbose: bool,
) -> str:
    prompt = build_prepare_discussion_prompt(
        contract_markdown=contract_markdown,
        inspection=inspection,
        user_message=user_message,
    )
    return io.request_text(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        verbose=verbose,
        status_hint="Discussing smoke preparation...",
    )


def finalize_preparation(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    inspection: SmokeInspection,
    model: str | None,
    verbose: bool,
) -> SetupPreparation:
    return io.request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=build_prepare_finalize_prompt(contract_markdown, inspection),
        model_type=SetupPreparation,
        model=model,
        verbose=verbose,
        status_hint="Finalizing smoke preparation...",
    )


def request_patch(
    *,
    base_url: str,
    session_id: str,
    contract_markdown: str,
    inspection: SmokeInspection,
    preparation: SetupPreparation,
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
        preparation=preparation,
        run_label=run_label,
        metric_tag=metric_tag,
        previous_patch_result=previous_patch_result,
        log_tail=log_tail,
    )
    return io.request_structured(
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
    resolved_command = command
    local_python = cwd / ".venv" / "bin" / "python"
    local_python3 = cwd / ".venv" / "bin" / "python3"
    if local_python.exists():
        current_python = str(local_python)
    elif local_python3.exists():
        current_python = str(local_python3)
    else:
        current_python = sys.executable
    command_match = re.match(
        r"^((?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+\s+)*)((?:python3|python))\s+(.*)$",
        command,
    )
    if command_match:
        env_prefix, _, remainder = command_match.groups()
        resolved_command = f'{env_prefix}"{current_python}" {remainder}'

    temp_log_path = logs_dir(cwd) / "setup_smoke_pending.log"
    with temp_log_path.open("w", encoding="utf-8") as log_handle:
        env = os.environ.copy()
        env["ARH_EXP_NUM"] = str(run_label)
        env["ARH_METRIC_TAG"] = metric_tag
        env["ARH_SMOKE"] = "1"
        python_bin = str(Path(current_python).parent)
        env["PATH"] = python_bin + os.pathsep + env.get("PATH", "")
        process = subprocess.Popen(
            resolved_command,
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
        "command": resolved_command,
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

        user_message = (
            "Inspect the training entrypoint and summarize the setup context."
        )
        while True:
            try:
                reply = request_inspection(
                    base_url=base_url,
                    session_id=session_id,
                    contract_markdown=contract_markdown,
                    user_message=user_message,
                    model=model,
                    verbose=verbose,
                )
            except io.StructuredResponseError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            print(reply)
            try:
                user_input = sanitize_user_input(input("> "))
            except EOFError:
                user_input = "quit"

            if user_input.lower() == "quit":
                return {"status": "cancelled", "session_id": session_id}
            if user_input.lower() == "confirm":
                inspection = finalize_inspection(
                    base_url=base_url,
                    session_id=session_id,
                    contract_markdown=contract_markdown,
                    model=model,
                    verbose=verbose,
                )
                print_inspection(inspection)
                if inspection.ready_for_confirmation:
                    break
                print(inspection.next_question)
                try:
                    user_message = sanitize_user_input(input("> "))
                except EOFError:
                    user_message = "quit"
                if user_message.lower() == "quit":
                    return {"status": "cancelled", "session_id": session_id}
                continue
            user_message = user_input or "Please continue."

        inspection = sanitize_inspection(inspection)
        print_inspection(inspection)

        user_message = (
            "Prepare the minimal smoke patch plan based on the confirmed inspection."
        )
        while True:
            try:
                reply = request_preparation(
                    base_url=base_url,
                    session_id=session_id,
                    contract_markdown=contract_markdown,
                    inspection=inspection,
                    user_message=user_message,
                    model=model,
                    verbose=verbose,
                )
            except io.StructuredResponseError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            print(reply)
            try:
                user_input = sanitize_user_input(input("> "))
            except EOFError:
                user_input = "quit"

            if user_input.lower() == "quit":
                return {"status": "cancelled", "session_id": session_id}
            if user_input.lower() == "confirm":
                preparation = finalize_preparation(
                    base_url=base_url,
                    session_id=session_id,
                    contract_markdown=contract_markdown,
                    inspection=inspection,
                    model=model,
                    verbose=verbose,
                )
                print_preparation(preparation)
                if preparation.ready_for_confirmation:
                    break
                print(preparation.next_question)
                try:
                    user_message = sanitize_user_input(input("> "))
                except EOFError:
                    user_message = "quit"
                if user_message.lower() == "quit":
                    return {"status": "cancelled", "session_id": session_id}
                continue
            user_message = user_input or "Please continue."

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
                preparation=preparation,
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

            if patch_result.status == "needs_user_action" and smoke_result is not None:
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
            print("\nRunning smoke command...")
            print(f"- command: {preparation.smoke_command}")
            smoke_result = run_smoke_command(
                cwd=cwd,
                command=preparation.smoke_command,
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
