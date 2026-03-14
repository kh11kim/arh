from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__
from .core import run_opencode_smoke
from .phases import contract as contract_phase
from .phases import feedback as feedback_phase
from .phases import research as research_phase
from .phases import research_loop as research_loop_phase
from .phases import setup as setup_phase


app = typer.Typer(
    help="Autoresearch CLI for contract setup, smoke setup, research runs, and feedback."
)
opencode_app = typer.Typer(help="Low-level OpenCode connectivity helpers.")
app.add_typer(opencode_app, name="opencode")


def cwd() -> Path:
    return Path(".").resolve()


def _handle_common_file_not_found(exc: FileNotFoundError) -> None:
    message = str(exc)
    typer.secho(message, fg=typer.colors.RED, err=True)
    if "contract file not found" in message:
        typer.secho(
            "Run `arh contract` first to create `research.md`, or pass `--contract <path>`.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    raise typer.Exit(code=1)


@app.command(help="Interactively create or update `research.md`, the project contract.")
def contract(
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    output: str = typer.Option(
        "research.md", help="Path to write the contract markdown."
    ),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed internal streaming events."
    ),
) -> None:
    result = contract_phase.run(
        cwd(),
        host=host,
        port=port,
        output_path=output,
        model=model,
        verbose=verbose,
    )
    print(f"status: {result['status']}")
    print(f"session_id: {result['session_id']}")
    if "output_path" in result:
        print(f"saved_to: {result['output_path']}")


@app.command(
    help="Inspect the training entrypoint, patch smoke instrumentation, and run setup smoke."
)
def setup(
    contract: str = typer.Option("research.md", help="Path to the contract markdown."),
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed internal streaming events."
    ),
) -> None:
    try:
        result = setup_phase.run(
            cwd(),
            contract_path=contract,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
        )
    except FileNotFoundError as exc:
        _handle_common_file_not_found(exc)
    print(f"status: {result['status']}")
    print(f"session_id: {result['session_id']}")
    if "smoke_result" in result:
        smoke_result = result["smoke_result"]
        print(f"log_path: {smoke_result['log_path']}")
        print(f"command: {smoke_result['command']}")
    if "result_marker" in result and result["result_marker"]:
        print(f"result: {result['result_marker']}")
    if "git" in result:
        print(f"git: {result['git']}")


@app.command(
    help="Create the next experiment, patch the repo, commit it, and launch the run in tmux."
)
def research(
    contract: str = typer.Option("research.md", help="Path to the contract markdown."),
    results: str = typer.Option(
        "results.md", help="Path to the experiment results log markdown."
    ),
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed internal streaming events."
    ),
) -> None:
    try:
        result = research_phase.run(
            cwd(),
            contract_path=contract,
            results_path=results,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
        )
    except FileNotFoundError as exc:
        _handle_common_file_not_found(exc)
    print(f"status: {result['status']}")
    if "exp_id" in result:
        print(f"exp_id: {result['exp_id']}")
    if "session_id" in result:
        print(f"session_id: {result['session_id']}")
    if "commit" in result:
        print(f"commit: {result['commit']}")
    if "polling_interval_seconds" in result:
        print(f"polling_interval_seconds: {result['polling_interval_seconds']}")
    if "tmux_session_name" in result and "launch" not in result:
        print(f"tmux_session_name: {result['tmux_session_name']}")
    if "launch" in result and result["launch"]:
        launch = result["launch"]
        print(f"tmux_session_name: {launch['tmux_session_name']}")
        print(f"log_path: {launch['log_path']}")
        print(f"command: {launch['command']}")
    if result.get("log_tail"):
        print("log_tail:")
        print(result["log_tail"])


@app.command(
    help="Inspect the latest finished run, append feedback, and suggest the next action."
)
def feedback(
    contract: str = typer.Option("research.md", help="Path to the contract markdown."),
    results: str = typer.Option(
        "results.md", help="Path to the experiment results log markdown."
    ),
    exp_id: int | None = typer.Option(None, help="Specific experiment id to inspect."),
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed internal streaming events."
    ),
) -> None:
    try:
        result = feedback_phase.run(
            cwd(),
            contract_path=contract,
            results_path=results,
            exp_id=exp_id,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
        )
    except FileNotFoundError as exc:
        _handle_common_file_not_found(exc)
    print(f"status: {result['status']}")
    if "exp_id" in result:
        print(f"exp_id: {result['exp_id']}")
    if result.get("status") == "running" and "next_phase" in result:
        print(f"next_phase: {result['next_phase']}")
    if result.get("status") == "running" and "suggested_sleep_sec" in result:
        print(f"suggested_sleep_sec: {result['suggested_sleep_sec']}")
    if "tmux_session_name" in result:
        print(f"tmux_session_name: {result['tmux_session_name']}")
    if "log_path" in result:
        print(f"log_path: {result['log_path']}")
    if "result_marker" in result and result["result_marker"]:
        print(f"result: {result['result_marker']}")
    if "summary" in result:
        summary = result["summary"]
        print(f"main_metric_value: {summary.main_metric}")
        print(f"sub_metric_value: {summary.sub_metric}")
        print(f"status_decision: {summary.status}")
        print(f"branch_action: {summary.branch_action}")
        if summary.accepted_commit:
            print(f"accepted_commit: {summary.accepted_commit}")
        print(f"description: {summary.description}")


@app.command(
    "research-loop",
    help="Continuously alternate feedback and research phases until stopped or a stop condition is reached.",
)
def research_loop(
    contract: str = typer.Option("research.md", help="Path to the contract markdown."),
    results: str = typer.Option(
        "results.md", help="Path to the experiment results log markdown."
    ),
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed internal streaming events."
    ),
    max_cycles: int = typer.Option(
        0, help="Stop after N loop cycles. Use 0 for no explicit cycle limit."
    ),
) -> None:
    try:
        result = research_loop_phase.run(
            cwd(),
            contract_path=contract,
            results_path=results,
            host=host,
            port=port,
            model=model,
            verbose=verbose,
            max_cycles=max_cycles,
        )
    except FileNotFoundError as exc:
        _handle_common_file_not_found(exc)
    print(f"status: {result['status']}")
    if "reason" in result:
        print(f"reason: {result['reason']}")
    if "stop_condition" in result:
        print(f"stop_condition: {result['stop_condition']}")
    if "completed_runs" in result:
        print(f"completed_runs: {result['completed_runs']}")
    if "cycles" in result:
        print(f"cycles: {result['cycles']}")
    if "exp_id" in result:
        print(f"exp_id: {result['exp_id']}")
    if result.get("final_summary"):
        print(f"final_summary: {result['final_summary']}")


@opencode_app.command(
    "smoke",
    help="Start a local OpenCode server, send one test prompt, and print the raw reply.",
)
def opencode_smoke(
    host: str = typer.Option("127.0.0.1", help="OpenCode server hostname"),
    port: int = typer.Option(4096, help="OpenCode server port"),
    prompt: str = typer.Option(
        "Say hello in one short sentence.", help="Test prompt to send."
    ),
    model: str = typer.Option(
        "openai/gpt-5.3-codex-spark",
        help="Model in provider/model format.",
    ),
) -> None:
    result = run_opencode_smoke(prompt=prompt, host=host, port=port, model=model)
    print(f"base_url: {result['base_url']}")
    print(f"session_id: {result['session_id']}")
    print(f"reply_text: {result['reply_text'] or '(empty)'}")
    print("raw_message:")
    print(json.dumps(result["message"], ensure_ascii=False, indent=2))


@app.command(help="Print the installed ARH version.")
def version() -> None:
    print(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
