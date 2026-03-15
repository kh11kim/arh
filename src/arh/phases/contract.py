from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .. import io
from ..opencode import create_session, start_server, stop_process, wait_for_health
from ..schema import ContractState, DEFAULT_RESEARCH_MD, empty_contract_state


def sanitize_user_input(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
    return cleaned.strip()


def build_contract_discussion_prompt(
    user_message: str, current_state: ContractState
) -> str:
    template = io.load_prompt("contract_discussion.md")
    return io.render_prompt(
        template,
        current_state_json=current_state.as_prompt_json(),
        user_message=user_message.strip(),
    )


def build_contract_finalize_prompt() -> str:
    return io.load_prompt("contract_finalize.md")


def render_research_markdown(state: ContractState) -> str:
    tie_breaker = state.evaluation.tie_breaker or "None"
    allowed = state.allowed_modifications or ["None specified"]
    forbidden = state.forbidden_modifications or ["everything else"]

    lines = [
        "# Research Goal",
        state.research_goal or "TBD",
        "",
        "# Evaluation",
        f"- main metric tag: {state.evaluation.main_metric or 'TBD'}",
        f"- direction: {state.evaluation.direction or 'TBD'}",
        f"- tie-breaker metric tag: {tie_breaker}",
        "",
        "# Execution",
        f"- experiment time: {state.execution.experiment_time or 'TBD'}",
        f"- train entrypoint: {state.execution.train_entrypoint or 'TBD'}",
        "",
        "# Stop Condition",
        state.stop_condition or "infinite",
        "",
        "# Allowed Modifications",
    ]
    lines.extend([f"- {item}" for item in allowed])
    lines.extend(["", "# Forbidden Modifications"])
    lines.extend([f"- {item}" for item in forbidden])
    return "\n".join(lines)


def print_contract_intro() -> None:
    print("OpenCode contract session started.")
    print("Describe your research goal freely. Type `quit` to exit.")


def print_contract_state(state: ContractState) -> None:
    print("\nCurrent understanding:\n")
    print(f"- goal: {state.research_goal or '(not set)'}")
    print(
        "- evaluation tags: "
        f"main={state.evaluation.main_metric or '(not set)'}, "
        f"direction={state.evaluation.direction or '(not set)'}, "
        f"tie_breaker={state.evaluation.tie_breaker or 'None'}"
    )
    print(
        "- execution: "
        f"time={state.execution.experiment_time or '(not set)'}, "
        f"entrypoint={state.execution.train_entrypoint or '(not set)'}"
    )
    print(f"- stop_condition: {state.stop_condition or '(not set)'}")
    allowed = ", ".join(state.allowed_modifications) or "(not set)"
    forbidden = ", ".join(state.forbidden_modifications) or "(not set)"
    print(f"- allowed: {allowed}")
    print(f"- forbidden: {forbidden}")
    print()


def should_preview_contract_state(reply: str) -> bool:
    text = reply.lower()
    markers = (
        "confirm",
        "검토 상태",
        "계약이 거의 완성",
        "계약 수집이 완료",
        "provide edits",
        "수정할 항목",
    )
    return any(marker in text for marker in markers)


def request_contract_turn(
    base_url: str,
    session_id: str,
    user_message: str,
    current_state: ContractState,
    model: str | None,
    verbose: bool,
) -> str:
    prompt = build_contract_discussion_prompt(user_message, current_state)
    return io.request_text(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        verbose=verbose,
        status_hint="Discussing research contract...",
    )


def finalize_contract(
    base_url: str,
    session_id: str,
    model: str | None,
    verbose: bool,
) -> ContractState:
    return io.request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=build_contract_finalize_prompt(),
        model_type=ContractState,
        model=model,
        verbose=verbose,
        status_hint="Finalizing research contract...",
    )


def run(
    cwd: Path,
    host: str = "127.0.0.1",
    port: int = 4096,
    output_path: str = DEFAULT_RESEARCH_MD,
    model: str | None = None,
    verbose: bool = False,
) -> dict[str, object]:
    parsed = urlparse(f"http://{host}:{port}")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    process = start_server(host=host, port=port)

    try:
        wait_for_health(base_url)
        session = create_session(base_url, title="arh contract")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")

        print_contract_intro()

        try:
            user_message = sanitize_user_input(input("> "))
        except EOFError:
            user_message = "quit"

        if not user_message or user_message.lower() == "quit":
            return {
                "status": "cancelled",
                "session_id": session_id,
                "base_url": base_url,
            }

        current_state = empty_contract_state()
        while True:
            reply = request_contract_turn(
                base_url=base_url,
                session_id=session_id,
                user_message=user_message,
                current_state=current_state,
                model=model,
                verbose=verbose,
            )
            if should_preview_contract_state(reply):
                try:
                    current_state = finalize_contract(
                        base_url=base_url,
                        session_id=session_id,
                        model=model,
                        verbose=verbose,
                    )
                except io.StructuredResponseError:
                    print(reply)
                else:
                    print_contract_state(current_state)
                    print("Reply `confirm` to save this contract, or provide edits.")
            else:
                print(reply)

            try:
                user_input = sanitize_user_input(input("> "))
            except EOFError:
                user_input = "quit"

            if not user_input:
                user_input = "Please continue."
            if user_input.lower() == "quit":
                return {
                    "status": "cancelled",
                    "session_id": session_id,
                    "base_url": base_url,
                    "state": current_state,
                }

            if user_input.lower() == "confirm":
                current_state = finalize_contract(
                    base_url=base_url,
                    session_id=session_id,
                    model=model,
                    verbose=verbose,
                )
                print_contract_state(current_state)
                if current_state.ready_for_review:
                    target = cwd / output_path
                    draft = render_research_markdown(current_state)
                    target.write_text(draft + "\n", encoding="utf-8")
                    return {
                        "status": "saved",
                        "session_id": session_id,
                        "base_url": base_url,
                        "output_path": str(target),
                        "draft": draft,
                        "state": current_state,
                    }
                print(current_state.next_question)
                try:
                    user_message = sanitize_user_input(input("> "))
                except EOFError:
                    user_message = "quit"
                if not user_message or user_message.lower() == "quit":
                    return {
                        "status": "cancelled",
                        "session_id": session_id,
                        "base_url": base_url,
                        "state": current_state,
                    }
                continue

            user_message = user_input
    finally:
        stop_process(process)
